"""Ryu (OpenFlow 1.3) controller - Packet Loss Detection and Recovery.

 * Proactively installs forwarding rules (h1 <-> h2) along the PRIMARY path.
 * Monitors the links by comparing tx (sender switch) vs rx (receiver switch) port counters.
 * Listens on a Unix datagram socket for loss alerts from the UDP receiver; on an alert it
   re-programs s1 and s4 so both directions use the ALTERNATE path.

Run:  ryu-manager controller.py
"""
import json, os, socket, time
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib import hub

H1, H2 = "10.0.0.1", "10.0.0.2"
CTRL_SOCK = "/tmp/sdn_ctrl.sock"
EVENT_LOG = "results/controller_events.log"

# Topology (ports):  h1-s1:1 | s1:2-s2:1 | s1:3-s3:1 | s2:2-s4:1 | s3:2-s4:2 | s4:3-h2
STATIC_FLOWS = {1: {H1: 1}, 2: {H2: 2, H1: 1}, 3: {H2: 2, H1: 1}, 4: {H2: 3}}
PATHS = {
    "primary":   {1: {H2: 2}, 4: {H1: 1}},   # s1-s2-s4
    "alternate": {1: {H2: 3}, 4: {H1: 2}},   # s1-s3-s4
}
LINKS = {"s1->s2 (primary)": (1, 2, 2, 1), "s1->s3 (alternate)": (1, 3, 3, 1)}


class LossRecoveryController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dps, self.stats, self.prev = {}, {}, {}
        self.current = "primary"
        os.makedirs("results", exist_ok=True)
        hub.spawn(self._alert_server)
        hub.spawn(self._monitor)

    def log(self, msg):
        line = f"{time.time():.3f} {msg}"
        self.logger.info(line)
        with open(EVENT_LOG, "a") as f:
            f.write(line + "\n")

    # ---------- flow programming ----------
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def on_switch(self, ev):
        dp = ev.msg.datapath
        self.dps[dp.id] = dp
        self.current = "primary"
        for ip, port in STATIC_FLOWS.get(dp.id, {}).items():
            self._add_flow(dp, ip, port)
        for ip, port in PATHS["primary"].get(dp.id, {}).items():
            self._add_flow(dp, ip, port)
        self.log(f"switch s{dp.id} connected; primary path installed")

    def _add_flow(self, dp, ip, out_port, priority=10):
        p, o = dp.ofproto_parser, dp.ofproto
        match = p.OFPMatch(eth_type=0x0800, ipv4_dst=ip)
        inst = [p.OFPInstructionActions(o.OFPIT_APPLY_ACTIONS, [p.OFPActionOutput(out_port)])]
        # same match + priority => existing entry is replaced (path switch)
        dp.send_msg(p.OFPFlowMod(datapath=dp, priority=priority, match=match, instructions=inst))

    def _reroute(self, to, reason):
        if self.current == to:
            return
        self.current = to
        for dpid, table in PATHS[to].items():
            for ip, port in table.items():
                self._add_flow(self.dps[dpid], ip, port)
        self.log(f"REROUTE -> {to} path ({reason})")

    # ---------- socket-application <-> SDN integration ----------
    def _alert_server(self):
        if os.path.exists(CTRL_SOCK):
            os.unlink(CTRL_SOCK)
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        s.bind(CTRL_SOCK)
        os.chmod(CTRL_SOCK, 0o777)
        self.log(f"listening for loss alerts on {CTRL_SOCK}")
        while True:
            data, _ = s.recvfrom(1024)
            try:
                msg = json.loads(data.decode())
            except ValueError:
                continue
            if msg.get("event") == "loss_alert":
                self.log(f"loss alert from receiver: loss={msg.get('loss'):.0%} seq={msg.get('seq')}")
                self._reroute("alternate", "UDP loss alert")

    # ---------- path monitoring ----------
    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def on_port_stats(self, ev):
        for s in ev.msg.body:
            self.stats[(ev.msg.datapath.id, s.port_no)] = (s.tx_packets, s.rx_packets)

    def _monitor(self):
        while True:
            hub.sleep(2)
            for dp in list(self.dps.values()):
                dp.send_msg(dp.ofproto_parser.OFPPortStatsRequest(dp, 0, dp.ofproto.OFPP_ANY))
            hub.sleep(0.5)
            for name, (a, pa, b, pb) in LINKS.items():
                tx = self.stats.get((a, pa), (None,))[0]
                rx = self.stats.get((b, pb), (None, None))[1]
                if tx is None or rx is None:
                    continue
                ptx, prx = self.prev.get(name, (tx, rx))
                self.prev[name] = (tx, rx)
                dtx, drx = tx - ptx, rx - prx
                if dtx >= 10:
                    self.log(f"[monitor] {name}: tx={dtx} rx={drx} loss={max(0, dtx - drx) / dtx:.0%}")

#!/usr/bin/env python3
"""Mininet topology + experiment runner.   Needs root:  sudo python3 topo.py --mode both

            +-- s2 --+            primary   path: s1-s2-s4
   h1 -- s1            s4 -- h2
            +-- s3 --+            alternate path: s1-s3-s4
"""
import argparse, os, threading, time
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel, info

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results")
PRIMARY = dict(bw=10, delay="5ms")
ALTERNATE = dict(bw=10, delay="10ms")


def build():
    net = Mininet(controller=None, link=TCLink, switch=OVSSwitch, autoSetMacs=True)
    net.addController("c0", controller=RemoteController, ip="127.0.0.1", port=6653)
    h1 = net.addHost("h1", ip="10.0.0.1/24")
    h2 = net.addHost("h2", ip="10.0.0.2/24")
    s1, s2, s3, s4 = [net.addSwitch(f"s{i}", dpid=f"{i:016x}", protocols="OpenFlow13") for i in (1, 2, 3, 4)]
    net.addLink(h1, s1, port2=1)
    net.addLink(s1, s2, port1=2, port2=1, **PRIMARY)
    net.addLink(s1, s3, port1=3, port2=1, **ALTERNATE)
    net.addLink(s2, s4, port1=2, port2=1, **PRIMARY)
    net.addLink(s3, s4, port1=2, port2=2, **ALTERNATE)
    net.addLink(s4, h2, port1=3)
    return net


def run_experiment(mode, a):
    info(f"\n===== experiment: {mode} =====\n")
    net = build()
    net.start()
    net.waitConnected()
    net.staticArp()                      # no ARP flooding needed in this loop-free flow design
    time.sleep(2)
    h1, h2, s1, s2 = net.get("h1", "h2", "s1", "s2")
    if net.ping([h1, h2], timeout="2") > 0:
        info("!!! h1 cannot reach h2 - is ryu-manager running?\n")
    link = net.linksBetween(s1, s2)[0]

    def inject():
        if a.fault == "down":
            info("*** FAULT: link s1-s2 DOWN\n")
            net.configLinkStatus("s1", "s2", "down")
        else:
            info(f"*** FAULT: {a.loss}% loss on s1-s2\n")
            for intf in (link.intf1, link.intf2):   # re-specify bw/delay: config() resets the qdisc
                intf.config(loss=a.loss, **PRIMARY)

    prefix = os.path.join(RESULTS, mode)
    log = open(prefix + "_console.log", "w")
    rcv_cmd = ["python3", os.path.join(HERE, "receiver.py"), "--out", prefix]
    if mode == "static":
        rcv_cmd.append("--no-alert")
    rcv = h2.popen(rcv_cmd, cwd=HERE, stdout=log, stderr=log)
    time.sleep(1)
    snd = h1.popen(["python3", os.path.join(HERE, "sender.py"), "--dst", "10.0.0.2",
                    "--count", str(a.count), "--rate", str(a.rate), "--out", prefix],
                   cwd=HERE, stdout=log, stderr=log)
    timer = threading.Timer(a.fault_at, inject)
    timer.start()
    snd.wait()
    timer.cancel()
    rcv.wait()
    log.close()
    net.stop()
    info(f"results written to {prefix}_*.json / _windows.csv\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["dynamic", "static", "both", "cli"], default="both")
    ap.add_argument("--count", type=int, default=750)
    ap.add_argument("--rate", type=float, default=50)
    ap.add_argument("--fault", choices=["loss", "down"], default="loss")
    ap.add_argument("--loss", type=int, default=30, help="%% loss injected on primary link")
    ap.add_argument("--fault-at", type=float, default=4.0, help="seconds after sender start")
    a = ap.parse_args()
    setLogLevel("info")
    os.makedirs(RESULTS, exist_ok=True)
    if a.mode == "cli":
        net = build(); net.start(); net.waitConnected(); net.staticArp()
        CLI(net); net.stop()
        return
    for m in (["dynamic", "static"] if a.mode == "both" else [a.mode]):
        run_experiment(m, a)


if __name__ == "__main__":
    main()

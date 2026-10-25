# Packet Loss Detection and Recovery: SDN + UDP Socket Programming

A UDP application detects packet loss with sequence numbers, retransmits lost packets,
and signals an SDN controller, which reroutes traffic onto an alternate Mininet path.

## Architecture
```
              +--- s2 ---+       primary   s1-s2-s4  (5 ms links)
 h1 --- s1                s4 --- h2
 sender       +--- s3 ---+       alternate s1-s3-s4  (10 ms links)       receiver

 receiver --(loss alert, Unix datagram socket)--> Ryu controller --(OpenFlow 1.3 FlowMod)--> s1, s4
```
| File | Role |
|---|---|
| `sender.py` | UDP sender: sequence numbers, per-packet ACKs, timeout retransmission, latency stats |
| `receiver.py` | ACKs, detects gaps/loss per window, alerts controller, measures detection and recovery time |
| `controller.py` | Ryu app: installs primary path, monitors link counters, reroutes on alert |
| `topo.py` | Mininet topology + automated experiment (loss or link-down fault injection) |
| `plot.py` | Static vs dynamic comparison table + graph |
| `proto.py` | Shared packet header |

## Setup (Ubuntu/Debian VM; Mininet needs Linux. On a Mac use UTM/Multipass/VirtualBox)
```bash
sudo apt install mininet openvswitch-switch python3-pip python3-matplotlib
pip3 install ryu eventlet==0.30.2      # the eventlet pin fixes Ryu's import error on newer Pythons
```

## Run
```bash
# terminal 1: controller (start it from this folder)
ryu-manager controller.py

# terminal 2: both experiments (dynamic then static baseline)
sudo python3 topo.py --mode both                 # 30% loss injected on s1-s2 after 4 s
sudo python3 topo.py --mode both --fault down    # challenging scenario: link failure
python3 plot.py                                  # table + results/loss_comparison.png
```
Manual demo: `sudo python3 topo.py --mode cli`, then in the Mininet CLI:
`h2 python3 receiver.py &` and `h1 python3 sender.py --dst 10.0.0.2 --count 750`, and try `link s1 s2 down`.
Useful for showing flows: `sudo ovs-ofctl -O OpenFlow13 dump-flows s1`.

## How it works
1. **Sequence tracking** – every DATA packet has `seq`, timestamp, and a retransmit flag.
2. **Detecting missing packets** – the receiver checks windows of 20 original packets; the loss rate is the fraction never received as first transmissions. A silence longer than 1 s is treated as total loss (link failure).
3. **ACK + retransmission** – each packet is ACKed; the sender retransmits after 250 ms, up to 10 tries.
4. **Monitoring** – the controller polls port counters and logs tx/rx packet counts per link, showing which path carries traffic. Loss itself is measured by the receiver, because the injected loss is dropped before the port counters see it.
5. **Dynamic rerouting** – on loss >= 15%, the receiver sends an alert to the controller, which replaces the flow entries on s1 (h1->h2) and s4 (h2->h1) to use s1-s3-s4.
6. **Metrics** – detection time, recovery time (10 in-order packets after the alert), loss before/after recovery, retransmissions, latency, vs a static no-reroute baseline.

## Rubric mapping
| Component | Where |
|---|---|
| Problem understanding & architecture | diagram above, `topo.py` docstring |
| TCP/UDP socket implementation | `sender.py`, `receiver.py` (raw `socket`, ACKs, retransmission) |
| Mininet + SDN implementation | `topo.py`, `controller.py` |
| Socket-SDN integration | receiver alert -> controller -> flow update |
| Dynamic SDN functionality | rerouting + link monitoring |
| Challenging scenario | `--fault loss` and `--fault down` |
| Performance evaluation & comparison | `plot.py`, static baseline (`--no-alert`) |
| Documentation / demo | this README, `results/*_console.log`, `results/controller_events.log` |

## Notes
- The Unix socket works because Mininet hosts share the root filesystem; hosts can't otherwise reach a controller on 127.0.0.1.
- Static ARP and explicit flows keep the diamond topology loop-free without STP.
- Tunables: `--window`, `--threshold`, `--stall` (receiver), `--rto` (sender).

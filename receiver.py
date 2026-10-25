#!/usr/bin/env python3
"""UDP receiver.
 * ACKs every packet
 * detects loss from sequence-number gaps (sliding windows of original transmissions)
 * alerts the SDN controller (Unix datagram socket) so it reroutes traffic
 * measures detection time, recovery time and loss before/after recovery
"""
import argparse, csv, json, os, socket, time
from proto import HDR, DATA, ACK, FIN, CTRL_SOCK


def alert_controller(path, loss, seq):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        s.sendto(json.dumps({"event": "loss_alert", "loss": loss, "seq": seq}).encode(), path)
        return True
    except OSError as e:
        print(f"[receiver] cannot reach controller: {e}", flush=True)
        return False
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5005)
    ap.add_argument("--window", type=int, default=20, help="packets per loss window")
    ap.add_argument("--threshold", type=float, default=0.15, help="loss rate that triggers alert")
    ap.add_argument("--stall", type=float, default=1.0, help="silence (s) treated as total loss")
    ap.add_argument("--idle-exit", type=float, default=3.0)
    ap.add_argument("--no-alert", action="store_true", help="static baseline: never alert")
    ap.add_argument("--ctrl", default=CTRL_SOCK)
    ap.add_argument("--out", default="results/run")
    a = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", a.port))
    sock.settimeout(0.5)

    W, TOL = a.window, 3
    orig, got = set(), set()
    expected, highest, next_win, dups = 0, -1, 0, 0
    t0 = None
    last_rx = time.time()
    first_gap_t = alert_t = alert_seq = recovered_t = None
    run, prev_orig, done = 0, -1, False
    delays, windows = [], []

    while True:
        try:
            data, addr = sock.recvfrom(2048)
        except socket.timeout:
            now = time.time()
            if t0 is None:
                continue
            if done or now - last_rx > a.idle_exit:
                break
            if alert_t is None and not a.no_alert and now - last_rx > a.stall:
                print("[receiver] traffic stalled -> assuming path failure", flush=True)
                if alert_controller(a.ctrl, 1.0, highest):
                    alert_t, alert_seq = now, highest
                    first_gap_t = first_gap_t or last_rx
            continue

        now = time.time()
        last_rx = now
        t0 = t0 or now
        typ, retx, seq, ts = HDR.unpack_from(data)
        if typ == FIN:
            done = True
            continue
        if typ != DATA:
            continue
        sock.sendto(HDR.pack(ACK, retx, seq, ts), addr)

        if seq in got:
            dups += 1
            continue
        got.add(seq)
        delays.append(now - ts)
        if retx:
            continue                      # only original transmissions count for loss

        orig.add(seq)
        highest = max(highest, seq)
        if seq > expected and first_gap_t is None:
            first_gap_t = now             # first missing packet noticed
        expected = max(expected, seq + 1)

        if alert_t is not None and recovered_t is None:
            run = run + 1 if seq == prev_orig + 1 else 1
            if run >= 10:
                recovered_t = now         # 10 in-order originals after reroute
        prev_orig = seq

        while highest >= (next_win + 1) * W + TOL:        # evaluate finished windows
            lo = next_win * W
            rate = sum(1 for s in range(lo, lo + W) if s not in orig) / W
            windows.append((next_win, lo, round(now - t0, 3), rate))
            print(f"[receiver] window {next_win:3d}  t={now - t0:6.2f}s  loss={rate:5.0%}", flush=True)
            if rate >= a.threshold and alert_t is None and not a.no_alert:
                if alert_controller(a.ctrl, rate, highest):
                    alert_t, alert_seq = now, highest
                    print(f"[receiver] >>> loss alert sent to controller (loss={rate:.0%})", flush=True)
            next_win += 1

    # ---------- results ----------
    rows = []
    for w, lo, t, rate in windows:
        phase = "static" if alert_seq is None else ("after" if lo > alert_seq + TOL else "before")
        rows.append((w, t, rate, phase))
    first_loss = next((w for w, _, r, _ in rows if r > 0), None)
    deg = [r for w, _, r, p in rows if first_loss is not None and w >= first_loss and p != "after"]
    aft = [r for _, _, r, p in rows if p == "after"]
    total = highest + 1
    rel = lambda t: round(t - t0, 3) if t else None
    summary = {
        "unique_delivered": len(got), "duplicates": dups,
        "first_pass_loss_pct": round(100 * (1 - len(orig) / total), 2) if total > 0 else None,
        "mean_delay_ms": round(1000 * sum(delays) / len(delays), 2) if delays else None,
        "loss_degraded_pct": round(100 * sum(deg) / len(deg), 1) if deg else 0.0,
        "loss_after_recovery_pct": round(100 * sum(aft) / len(aft), 1) if aft else None,
        "first_loss_at_s": rel(first_gap_t), "alert_at_s": rel(alert_t),
        "detection_time_s": round(alert_t - first_gap_t, 3) if alert_t and first_gap_t else None,
        "recovery_time_s": round(recovered_t - first_gap_t, 3) if recovered_t and first_gap_t else None,
    }
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out + "_windows.csv", "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["window", "t", "loss", "phase"])
        wr.writerows(rows)
    json.dump(summary, open(a.out + "_summary.json", "w"), indent=2)
    print("[receiver] summary", json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""UDP sender with sequence numbers, per-packet ACKs and timeout retransmission."""
import argparse, json, os, select, socket, time
from proto import HDR, DATA, ACK, FIN, PAYLOAD


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dst", default="10.0.0.2")
    ap.add_argument("--port", type=int, default=5005)
    ap.add_argument("--count", type=int, default=750)
    ap.add_argument("--rate", type=float, default=50, help="packets per second")
    ap.add_argument("--rto", type=float, default=0.25, help="retransmit timeout (s)")
    ap.add_argument("--max-tries", type=int, default=10)
    ap.add_argument("--out", default="results/run")
    a = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dst = (a.dst, a.port)
    unacked = {}                      # seq -> [first_sent, last_sent, tries]
    lat, retx, failed, next_seq = [], 0, 0, 0
    interval = 1.0 / a.rate
    t0 = time.time()
    next_send = t0

    while next_seq < a.count or unacked:
        now = time.time()
        if next_seq < a.count and now >= next_send:
            sock.sendto(HDR.pack(DATA, 0, next_seq, now) + PAYLOAD, dst)
            unacked[next_seq] = [now, now, 1]
            next_seq += 1
            next_send += interval

        wait = 0.01 if next_seq >= a.count else max(0.0, min(next_send - now, 0.01))
        ready, _, _ = select.select([sock], [], [], wait)
        while ready:                                   # drain ACKs
            data, _ = sock.recvfrom(2048)
            typ, _, seq, _ = HDR.unpack_from(data)
            if typ == ACK and seq in unacked:
                lat.append(time.time() - unacked.pop(seq)[0])
            ready, _, _ = select.select([sock], [], [], 0)

        now = time.time()
        for seq, v in list(unacked.items()):           # retransmissions
            if now - v[1] > a.rto:
                if v[2] >= a.max_tries:
                    del unacked[seq]
                    failed += 1
                else:
                    sock.sendto(HDR.pack(DATA, 1, seq, v[0]) + PAYLOAD, dst)
                    v[1], v[2] = now, v[2] + 1
                    retx += 1

    dur = time.time() - t0
    for _ in range(5):                                 # tell receiver we're done
        sock.sendto(HDR.pack(FIN, 0, a.count, time.time()), dst)
        time.sleep(0.05)

    lat.sort()
    res = {
        "packets": a.count, "retransmissions": retx, "failed": failed,
        "duration_s": round(dur, 3),
        "mean_latency_ms": round(1000 * sum(lat) / len(lat), 2) if lat else None,
        "p95_latency_ms": round(1000 * lat[int(0.95 * (len(lat) - 1))], 2) if lat else None,
        "goodput_pps": round((a.count - failed) / dur, 2),
    }
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(res, open(a.out + "_sender.json", "w"), indent=2)
    print("[sender]", json.dumps(res), flush=True)


if __name__ == "__main__":
    main()

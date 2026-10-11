import json
import os
import shutil
import sys
import tempfile

import cv2
import numpy as np

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("  FAIL  %s" % msg)


def _write_json(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f)


def picture(w=320, h=240):
    img = np.full((h, w, 3), 90, np.uint8)
    cv2.rectangle(img, (40, 30), (90, 130), (18, 18, 18), -1)
    cv2.circle(img, (65, 55), 16, (30, 30, 235), -1)
    return cv2.imencode(".jpg", img)[1].tobytes()


def main():
    import lab as lab_mod
    root = tempfile.mkdtemp(prefix="suki-lab-")
    os.makedirs(os.path.join(root, "lab"), exist_ok=True)
    try:
        L = lab_mod.Lab(root, _write_json)
        rec, err = L.add(picture(), name="junction")
        check(err is None and rec, "the picture would not go in: %s" % err)
        iid = rec["id"]
        print("stored %s as %s (%dx%d)" % (rec["name"], iid, rec["w"], rec["h"]))

        img = cv2.imread(os.path.join(L.dir, iid + ".jpg"))
        from vision import classify_light_full
        box = [40, 30, 50, 100]
        det = {"label": "traffic light", "conf": 0.91, "box": box,
               "light": classify_light_full(img[30:130, 40:90])}
        check(det["light"]["colour"] == "red",
              "the lamp in the test picture read as %r" % det["light"]["colour"])
        res = {"conf": 0.4, "imgsz": 640, "when": 0, "dets": [det], "error": None,
               "ms": 12, "light": dict(det["light"], n=1)}
        res["out"] = L._annotate(img, res, "yolo26n.pt", iid)
        L.runs.setdefault(iid, {})["yolo26n.pt"] = res
        L._save_runs()

        check(res["out"], "no annotated picture was written")
        out_path = os.path.join(L.dir, res["out"] or "")
        check(os.path.exists(out_path), "the annotated picture is not on the disk")
        if os.path.exists(out_path):
            back = cv2.imread(out_path)
            check(back is not None, "the annotated picture is not a readable JPEG")
            check(back is not None and back.shape[:2] == img.shape[:2],
                  "the annotated picture is a different size to the original")
            check(back is not None and int(np.abs(back.astype(int)
                                                  - img.astype(int)).sum()) > 10000,
                  "the annotated picture is identical to the original - nothing drawn")
            print("annotated picture: %s (%d bytes)"
                  % (res["out"], os.path.getsize(out_path)))

        ex = L.export(iid)
        check(ex, "export returned nothing")
        if ex:
            check(ex["files"]["original"].endswith(".jpg"), "no original in the export")
            check(ex["files"]["annotated"].get("yolo26n.pt"),
                  "the export does not point at the annotated picture")
            check(ex["runs"]["yolo26n.pt"]["dets"][0]["light"]["colour"] == "red",
                  "the export lost the traffic-light verdict")
            check(json.dumps(ex), "the export is not JSON-serialisable")
            print("export carries: %s" % ", ".join(sorted(ex.keys())))

        L2 = lab_mod.Lab(root, _write_json)
        check([i["id"] for i in L2.images] == [iid],
              "a fresh Lab did not find the picture")
        r2 = (L2.runs.get(iid) or {}).get("yolo26n.pt") or {}
        check(len(r2.get("dets") or []) == 1, "a fresh Lab did not find the detections")
        check((r2.get("light") or {}).get("colour") == "red",
              "a fresh Lab lost the traffic-light verdict")
        check(r2.get("out") == res["out"], "a fresh Lab lost the annotated picture")
        print("a second Lab on the same directory found the picture, its boxes, "
              "its light verdict and its annotated copy")

        L2.delete(iid)
        left = [f for f in os.listdir(L2.dir) if f.startswith(iid)]
        check(not left, "deleting the picture left %s behind" % left)
        check(iid not in L2.runs, "deleting the picture left its runs in lab_runs.json")
        print("deleting the picture removed its analysis and its annotated copy too")

        L3 = lab_mod.Lab(root, _write_json)
        L3.runs["ghost"] = {"yolo26n.pt": {"dets": []}}
        L3._save_runs()
        L4 = lab_mod.Lab(root, _write_json)
        check("ghost" not in L4.runs,
              "a run record whose picture is gone survived a reload")
        print("a run record with no picture is swept on the next start")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n%s" % ("FAILED: %d" % len(FAILS) if FAILS
                    else "all bench-storage checks passed"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())

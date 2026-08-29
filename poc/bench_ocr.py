#!/usr/bin/env python
"""Đo Apple Vision OCR (on-device, native macOS) trên ảnh chụp iPhone Mirroring.

Mục đích: so với Florence-2 <OCR_WITH_REGION> cho việc tìm nút Skip/Done/Đóng
trong quảng cáo. Vision không cần tải model, không cần train, chạy trên Neural
Engine, và trả về bounding box theo toạ độ chuẩn hoá 0..1.
"""
import sys
import time

import Quartz
import Vision
from Foundation import NSURL

PATH = sys.argv[1] if len(sys.argv) > 1 else "poc/out/real/cap_CGWindowListCreateImage.png"
LANGS = ["vi-VT", "en-US"]


def ocr(url, fast=False):
    """Trả về list (text, confidence, box_chuẩn_hoá)."""
    out = []

    def handler(request, error):
        for obs in request.results() or []:
            cand = obs.topCandidates_(1)
            if not cand:
                continue
            bb = obs.boundingBox()
            out.append((str(cand[0].string()), float(cand[0].confidence()),
                        (bb.origin.x, bb.origin.y, bb.size.width, bb.size.height)))

    req = Vision.VNRecognizeTextRequest.alloc().initWithCompletionHandler_(handler)
    req.setRecognitionLevel_(1 if fast else 0)   # 0=accurate, 1=fast
    req.setRecognitionLanguages_(LANGS)
    req.setUsesLanguageCorrection_(not fast)
    Vision.VNImageRequestHandler.alloc().initWithURL_options_(
        NSURL.fileURLWithPath_(url), None).performRequests_error_([req], None)
    return out


def main():
    img = Quartz.CGImageSourceCreateImageAtIndex(
        Quartz.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(PATH), None), 0, None)
    W, H = Quartz.CGImageGetWidth(img), Quartz.CGImageGetHeight(img)
    print(f"Ảnh: {PATH}  ({W}x{H})\n")

    for label, fast in (("accurate", False), ("fast", True)):
        ocr(PATH, fast)                      # warm-up
        t0 = time.perf_counter()
        for _ in range(10):
            res = ocr(PATH, fast)
        ms = (time.perf_counter() - t0) / 10 * 1000
        print(f"--- level={label}: {ms:.1f} ms/frame  ({1000/ms:.1f} FPS), "
              f"{len(res)} vùng chữ ---")
        for txt, conf, (bx, by, bw, bh) in res:
            # Vision dùng gốc toạ độ góc DƯỚI-trái, y hướng lên -> phải lật.
            cx = int((bx + bw / 2) * W)
            cy = int((1 - (by + bh / 2)) * H)
            print(f"    {conf:.2f}  tâm=({cx:>4},{cy:>4})  {txt!r}")
        print()


if __name__ == "__main__":
    main()

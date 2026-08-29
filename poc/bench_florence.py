#!/usr/bin/env python
"""Benchmark THẬT Florence-2-base cho tầng C (xử lý quảng cáo) trên máy này.

Đo: latency theo device/dtype/num_beams, số token sinh ra, RAM, và QUAN TRỌNG
NHẤT — model có tìm đúng nút đóng quảng cáo không, lệch bao nhiêu point.

Chạy:  ./.venv/bin/python poc/bench_florence.py
       ./.venv/bin/python poc/bench_florence.py --model florence-community/Florence-2-base-ft
"""
import argparse
import json
import os
import time
import warnings

warnings.filterwarnings("ignore")
import torch
from PIL import Image
from transformers import AutoProcessor, Florence2ForConditionalGeneration

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
REAL = os.path.join(OUT, "real", "cap_CGWindowListCreateImage.png")
FAKE = os.path.join(OUT, "fake_ad.png")

# Các task có thể dùng cho việc đóng quảng cáo.
TASKS = [
    ("<OCR_WITH_REGION>", None, "OCR + box"),
    ("<OD>", None, "object detection"),
    ("<CAPTION_TO_PHRASE_GROUNDING>", "close button", "grounding: close button"),
    ("<OPEN_VOCABULARY_DETECTION>", "close button", "open-vocab: close button"),
    ("<OPEN_VOCABULARY_DETECTION>", "small x icon", "open-vocab: small x icon"),
]


def rss_mb():
    import resource
    # macOS: ru_maxrss tính bằng BYTE (Linux thì là KB) -> chia 1024^2 ra MB
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)


def run_once(model, proc, image, task, text_input, beams, device, max_new=512):
    prompt = task if text_input is None else task + text_input
    inputs = proc(text=prompt, images=image, return_tensors="pt")
    inputs = {k: (v.to(device) if hasattr(v, "to") else v) for k, v in inputs.items()}
    if "pixel_values" in inputs and inputs["pixel_values"].dtype.is_floating_point:
        inputs["pixel_values"] = inputs["pixel_values"].to(model.dtype)
    with torch.inference_mode():
        ids = model.generate(**inputs, max_new_tokens=max_new,
                             num_beams=beams, do_sample=False)
    n_tok = int(ids.shape[-1])
    text = proc.batch_decode(ids, skip_special_tokens=False)[0]
    try:
        parsed = proc.post_process_generation(
            text, task=task, image_size=(image.width, image.height))
    except Exception as e:
        parsed = {"_parse_error": f"{type(e).__name__}: {e}"}
    return parsed, n_tok, text


def centers(parsed, task):
    """Rút (label, tâm_x, tâm_y) từ output đã parse."""
    d = parsed.get(task) if isinstance(parsed, dict) else None
    if not isinstance(d, dict):
        return []
    boxes = d.get("bboxes") or d.get("quad_boxes") or []
    labels = d.get("labels") or d.get("bboxes_labels") or [""] * len(boxes)
    out = []
    for b, lab in zip(boxes, labels):
        if len(b) == 4:
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        elif len(b) == 8:
            cx, cy = sum(b[0::2]) / 4, sum(b[1::2]) / 4
        else:
            continue
        out.append((str(lab), int(cx), int(cy)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="florence-community/Florence-2-base")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--fast", action="store_true",
                    help="chỉ chạy MPS fp16 + beams=1 (cấu hình bot sẽ dùng thật)")
    args = ap.parse_args()

    print("=" * 78)
    print(f"BENCHMARK FLORENCE-2  —  {args.model}")
    print(f"torch {torch.__version__}  MPS={torch.backends.mps.is_available()}")
    print("=" * 78)

    proc = AutoProcessor.from_pretrained(args.model)
    truth = json.load(open(os.path.join(OUT, "fake_ad_truth.json")))
    images = [("ad giả (410x898)", Image.open(FAKE).convert("RGB"))]
    if os.path.exists(REAL):
        images.append(("màn iPhone thật (410x898)", Image.open(REAL).convert("RGB")))

    configs = ([("mps", torch.float16)] if args.fast else
               [("cpu", torch.float32), ("mps", torch.float32), ("mps", torch.float16)])

    for dev, dt in configs:
        if dev == "mps" and not torch.backends.mps.is_available():
            continue
        print(f"\n{'#' * 78}\n# DEVICE={dev}  DTYPE={str(dt).split('.')[-1]}\n{'#' * 78}")
        t0 = time.perf_counter()
        try:
            model = Florence2ForConditionalGeneration.from_pretrained(
                args.model, dtype=dt).to(dev).eval()
        except Exception as e:
            print(f"  LOAD FAIL: {type(e).__name__}: {str(e)[:200]}")
            continue
        load_s = time.perf_counter() - t0
        n_par = sum(p.numel() for p in model.parameters())
        print(f"  load {load_s:.1f}s  params {n_par/1e6:.1f}M  RSS {rss_mb():.0f} MB")

        for beams in ((1,) if args.fast else (1, 3)):
            print(f"\n  --- num_beams={beams} "
                  f"{'(greedy, dùng cho bot)' if beams == 1 else '(mặc định trong doc HF)'} ---")
            hdr = f"  {'TASK':<30}{'ms':>9}{'tok':>6}   KẾT QUẢ"
            print(hdr)
            print("  " + "-" * (len(hdr) - 2))
            img_name, img = images[0]
            for task, ti, label in TASKS:
                try:
                    run_once(model, proc, img, task, ti, beams, dev, 64)  # warm-up
                    t0 = time.perf_counter()
                    for _ in range(args.reps):
                        parsed, n_tok, raw = run_once(model, proc, img, task, ti,
                                                      beams, dev)
                    ms = (time.perf_counter() - t0) / args.reps * 1000
                    cs = centers(parsed, task)
                    if not cs:
                        brief = str(parsed)[:70]
                    else:
                        parts = []
                        for lab, cx, cy in cs[:4]:
                            best = min(truth.items(),
                                       key=lambda kv: (kv[1][0]-cx)**2 + (kv[1][1]-cy)**2)
                            dist = ((best[1][0]-cx)**2 + (best[1][1]-cy)**2) ** 0.5
                            parts.append(f"{lab}@({cx},{cy})~{best[0]}(Δ{dist:.0f}pt)")
                        brief = "  ".join(parts)
                    print(f"  {label:<30}{ms:>9.0f}{n_tok:>6}   {brief}")
                except Exception as e:
                    print(f"  {label:<30}{'FAIL':>9}{'-':>6}   "
                          f"{type(e).__name__}: {str(e)[:60]}")
        # Test crop: cắt riêng góc trên-phải rồi hỏi. Vừa giảm số token sinh ra,
        # vừa làm nút X nhỏ chiếm tỉ lệ lớn hơn trong 768x768 -> dễ thấy hơn.
        print(f"\n  --- CROP góc trên-phải 130x130, num_beams=1 ---")
        img = images[0][1]
        crop_box = (img.width - 130, 0, img.width, 130)
        sub = img.crop(crop_box)
        for task, ti in [("<OCR_WITH_REGION>", None),
                         ("<OPEN_VOCABULARY_DETECTION>", "close button"),
                         ("<CAPTION_TO_PHRASE_GROUNDING>", "x")]:
            try:
                run_once(model, proc, sub, task, ti, 1, dev, 64)
                t0 = time.perf_counter()
                parsed, n_tok, _ = run_once(model, proc, sub, task, ti, 1, dev, 256)
                ms = (time.perf_counter() - t0) * 1000
                cs = centers(parsed, task)
                gt = truth["close_x_icon"]
                parts = []
                for lab, cx, cy in cs[:3]:
                    ax, ay = cx + crop_box[0], cy + crop_box[1]
                    d = ((gt[0]-ax)**2 + (gt[1]-ay)**2) ** 0.5
                    parts.append(f"{lab}@({ax},{ay}) Δ{d:.0f}pt")
                lbl = task + (f" '{ti}'" if ti else "")
                print(f"  {lbl:<44}{ms:>7.0f}ms {n_tok:>3}tok  "
                      f"{'  '.join(parts) or 'không thấy gì'}")
            except Exception as e:
                print(f"  {task:<44}{'FAIL':>7}     {type(e).__name__}: {str(e)[:50]}")

        del model
        if dev == "mps":
            torch.mps.empty_cache()

    print("\n" + "=" * 78)
    print("Ground truth ảnh ad giả:", truth)
    print("=" * 78)


if __name__ == "__main__":
    main()

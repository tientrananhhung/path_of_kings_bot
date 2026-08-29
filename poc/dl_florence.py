import time, warnings, torch
warnings.filterwarnings("ignore")
from transformers import AutoProcessor, Florence2ForConditionalGeneration
MID = "florence-community/Florence-2-base-ft"
t0 = time.time()
proc = AutoProcessor.from_pretrained(MID)
print(f"processor OK {time.time()-t0:.1f}s {type(proc).__name__}", flush=True)
t0 = time.time()
m = Florence2ForConditionalGeneration.from_pretrained(MID, dtype=torch.float32)
n = sum(p.numel() for p in m.parameters())
print(f"model OK {time.time()-t0:.1f}s params={n/1e6:.1f}M", flush=True)
print("DONE", flush=True)

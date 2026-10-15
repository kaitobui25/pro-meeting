"""Measure cached NLLB Japanese→Vietnamese translation on this Windows CPU."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import time

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--quantize', action='store_true')
    parser.add_argument('--text', default='一般的なトレーシングは先にやっちゃった方がいいですよね。')
    args = parser.parse_args()
    torch.set_num_threads(args.threads)
    snapshot = (Path.home() / '.cache/huggingface/hub/models--facebook--nllb-200-distilled-600M'
                / 'snapshots/f8d333a098d19b4fd9a8b18f94170487ad3f821d')
    start = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(str(snapshot), src_lang='jpn_Jpan', local_files_only=True)
    model = AutoModelForSeq2SeqLM.from_pretrained(str(snapshot), local_files_only=True)
    model.eval()
    if args.quantize:
        model = torch.ao.quantization.quantize_dynamic(model, {torch.nn.Linear}, dtype=torch.qint8)
    print('LOAD_SECONDS', round(time.perf_counter() - start, 2), flush=True)
    target = tokenizer.convert_tokens_to_ids('vie_Latn')
    print('VIETNAMESE_TOKEN_ID', target, flush=True)
    inputs = tokenizer(args.text, return_tensors='pt')
    start = time.perf_counter()
    with torch.inference_mode():
        translated = model.generate(**inputs, forced_bos_token_id=target,
                                    max_new_tokens=150, num_beams=1)
    print('TRANSLATE_SECONDS', round(time.perf_counter() - start, 2), flush=True)
    print('VIETNAMESE', tokenizer.batch_decode(translated, skip_special_tokens=True)[0], flush=True)


if __name__ == '__main__':
    main()

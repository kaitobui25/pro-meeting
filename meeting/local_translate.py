"""Low-latency Japanese→Vietnamese translation with a cached NLLB model."""

from __future__ import annotations

import os
from pathlib import Path
import re


def translation_groups(japanese: str, max_chars: int = 65) -> list[str]:
    """Small independent clauses prevent NLLB from looping over meeting monologues.

    Whisper line breaks mark a natural short speech segment. Keep neighboring
    clauses together when possible, but cap input context for NLLB's decoder.
    """
    if max_chars < 10:
        raise ValueError('max_chars quá ngắn')
    clauses = []
    for line in japanese.splitlines():
        for chunk in re.split(r'(?<=[。！？!?])', line):
            chunk = chunk.strip()
            if chunk:
                clauses.extend(chunk[i:i + max_chars] for i in range(0, len(chunk), max_chars))
    groups: list[str] = []
    current = ''
    for clause in clauses:
        if current and len(current) + len(clause) + 1 > max_chars:
            groups.append(current)
            current = ''
        current = f'{current} {clause}'.strip() if current else clause
    if current:
        groups.append(current)
    return groups


def cached_nllb_folder() -> Path:
    override = os.getenv('PRO_MEETING_NLLB_PATH')
    if override:
        directory = Path(override)
        if not directory.is_dir():
            raise RuntimeError(f'Không tìm thấy thư mục NLLB: {directory}')
        return directory
    snapshots = (Path.home() / '.cache' / 'huggingface' / 'hub'
                 / 'models--facebook--nllb-200-distilled-600M' / 'snapshots')
    for directory in sorted(snapshots.glob('*')):
        if ((directory / 'config.json').is_file()
                and (directory / 'tokenizer.json').is_file()
                and ((directory / 'model.safetensors').is_file()
                     or (directory / 'pytorch_model.bin').is_file())):
            return directory
    raise RuntimeError('Chưa có bộ NLLB Nhật–Việt trên máy. Dùng PRO_MEETING_ENGINE=hybrid để dịch qua Neo.')


class LocalJapaneseVietnamese:
    def __init__(self) -> None:
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        torch.set_num_threads(int(os.getenv('PRO_MEETING_NLLB_THREADS', '6')))
        folder = cached_nllb_folder()
        self.tokenizer = AutoTokenizer.from_pretrained(
            str(folder), src_lang='jpn_Jpan', local_files_only=True)
        model = AutoModelForSeq2SeqLM.from_pretrained(str(folder), local_files_only=True)
        model.eval()
        self.model = torch.ao.quantization.quantize_dynamic(
            model, {torch.nn.Linear}, dtype=torch.qint8)
        self.torch = torch
        self.vietnamese_id = self.tokenizer.convert_tokens_to_ids('vie_Latn')

    def translate(self, japanese: str) -> str:
        if not japanese.strip() or japanese.strip() == '....':
            return '....'
        pieces = []
        for group in translation_groups(japanese):
            tokens = self.tokenizer(group, return_tensors='pt', truncation=True,
                                    max_length=140)
            with self.torch.inference_mode():
                result = self.model.generate(
                    **tokens, forced_bos_token_id=self.vietnamese_id,
                    max_length=100, num_beams=1,
                    no_repeat_ngram_size=3, repetition_penalty=1.15)
            pieces.append(self.tokenizer.batch_decode(result, skip_special_tokens=True)[0].strip())
        return '\n'.join(pieces)

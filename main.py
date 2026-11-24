#!/usr/bin/env python3
"""Publish the one-sentence invention pitch for the make.fun
bounty "One-Sentence Absurd Invention Pitch".

The pitch lives in ``entry.txt`` next to this file: a
self-watering houseplant that files noise complaints. This
program reads that file as raw bytes, checks the decoded text
against the bounty gate (UTF-8 text, one sentence, 1 to 220
characters, not only white space), and writes the exact same
bytes to ``entry.txt`` in the output directory. Nothing is
stripped, trimmed, or re-encoded: the published bytes are
byte-identical to the source file, so the judge reads precisely
the pitch that was written. The publish is atomic (temporary
file, then rename), so a failure mid-write can never leave a
half-written entry behind.

Characters are counted as Unicode code points, the same way the
gate counts them; the byte length is reported beside the character
count so the two can never be confused. Standard library only, no
network, no clock, no randomness, so two runs always produce
identical output.

The output directory is ``--output-dir`` when given, else
``$MAKEFUN_OUTPUT_DIR`` when set, else ``/output``.

Options:
  --output-dir <dir>  write entry.txt into <dir> instead
  --max-chars <n>     check against a limit other than 220
  --verify-only       check the entry without writing anything
  --allow-multi       allow more than one sentence in the entry
  --json              print the report as JSON instead of text
  --quiet             print nothing on success (errors still show)

Exit codes: 0 success, 1 the entry fails the gate or the output
cannot be written, 2 a command-line argument is unusable.
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MAX_CHARS = 220


class EntryError(Exception):
    """The entry file fails the bounty gate."""


@dataclass(frozen=True)
class PitchReport:
    """What the gate check found in ``entry.txt``."""

    text: str
    byte_length: int
    trailing_newline: bool

    @property
    def char_length(self) -> int:
        return len(self.text)

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    @property
    def sentence_count(self) -> int:
        return sum(self.text.count(mark) for mark in ".!?")

    def summary(self) -> str:
        newline = "with" if self.trailing_newline else "without"
        return (
            f"{self.char_length} characters, "
            f"{self.byte_length} bytes, {self.word_count} words, "
            f"{self.sentence_count} sentence(s), "
            f"{newline} trailing newline"
        )

    def as_dict(self) -> dict:
        return {
            "characters": self.char_length,
            "bytes": self.byte_length,
            "words": self.word_count,
            "sentences": self.sentence_count,
            "trailing_newline": self.trailing_newline,
            "valid": True,
        }


def entry_path() -> Path:
    return Path(__file__).resolve().parent / "entry.txt"


def load_entry_bytes() -> bytes:
    try:
        return entry_path().read_bytes()
    except FileNotFoundError as exc:
        raise EntryError("entry.txt not found next to main.py") from exc
    except OSError as exc:
        raise EntryError(f"cannot read entry.txt: {exc}") from exc


@dataclass(frozen=True)
class GateConfig:
    """The bounty gate: one sentence of UTF-8 text within a limit."""

    max_chars: int = DEFAULT_MAX_CHARS
    min_chars: int = 1
    one_sentence: bool = True

    def problems(self, line: str) -> list:
        """Every way ``line`` fails the gate, in check order."""
        found = []
        if not line or line.isspace():
            found.append("entry is empty or only white space")
        if "\n" in line or "\r" in line:
            found.append("entry must be a single line")
        if len(line) < self.min_chars:
            found.append(
                f"entry is {len(line)} characters, "
                f"below the {self.min_chars} minimum"
            )
        if len(line) > self.max_chars:
            found.append(
                f"entry is {len(line)} characters, "
                f"over the {self.max_chars} limit"
            )
        sentences = sum(line.count(mark) for mark in ".!?")
        if self.one_sentence and sentences != 1:
            found.append(
                f"entry has {sentences} sentences, expected exactly one"
            )
        return found


def check_entry(data: bytes, gate: GateConfig) -> PitchReport:
    """Decode ``data`` and check it against the bounty gate.

    Every problem is reported at once, instead of stopping at the
    first one, so a single run shows the whole repair list.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EntryError(f"entry.txt is not valid UTF-8: {exc}") from exc
    trailing = text.endswith("\n")
    line = text[:-1] if trailing else text
    problems = gate.problems(line)
    if problems:
        raise EntryError("; ".join(problems))
    return PitchReport(
        text=line,
        byte_length=len(data),
        trailing_newline=trailing,
    )


def resolve_output_dir(cli_dir: str | None) -> Path:
    if cli_dir:
        return Path(cli_dir)
    env_dir = os.environ.get("MAKEFUN_OUTPUT_DIR")
    if env_dir:
        return Path(env_dir)
    return Path("/output")


def publish(data: bytes, out_dir: Path) -> Path:
    """Write ``data`` verbatim and verify it by reading it back.

    The write is atomic: the bytes go to a temporary file in the
    same directory and are renamed into place, so a crash or a
    failure mid-write can never leave a half-written ``entry.txt``
    behind for the judge to read.
    """
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise EntryError(f"cannot create output directory: {exc}") from exc
    target = out_dir / "entry.txt"
    staging = out_dir / ".entry.txt.tmp"
    try:
        staging.write_bytes(data)
        os.replace(staging, target)
        published = target.read_bytes()
    except OSError as exc:
        try:
            staging.unlink(missing_ok=True)
        except OSError:
            pass
        raise EntryError(f"cannot write entry.txt: {exc}") from exc
    if published != data:
        raise EntryError("published entry.txt differs from entry.txt")
    return target


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=None,
        help="directory to write entry.txt into",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=DEFAULT_MAX_CHARS,
        help="character limit to check against (default: 220)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="validate the entry without writing it",
    )
    parser.add_argument(
        "--allow-multi",
        action="store_true",
        help="allow more than one sentence in the entry",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the report as JSON instead of text",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="print nothing on success",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.max_chars < 1:
        print("error: --max-chars must be at least 1", file=sys.stderr)
        return 2
    try:
        data = load_entry_bytes()
        gate = GateConfig(
            max_chars=args.max_chars, one_sentence=not args.allow_multi
        )
        report = check_entry(data, gate)
        if args.verify_only:
            target = None
        else:
            target = publish(data, resolve_output_dir(args.output_dir))
    except EntryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not args.quiet:
        if args.json:
            payload = report.as_dict()
            if target is not None:
                payload["published_to"] = str(target)
            print(json.dumps(payload, indent=2))
        elif target is not None:
            print(f"published {report.summary()} to {target}")
        else:
            print(f"valid: {report.summary()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

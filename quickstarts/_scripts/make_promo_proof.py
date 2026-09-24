"""Write the synthetic promotion signage proof that quickstart 07 extracts and cross-checks (no dependencies).

    uv run python quickstarts/_scripts/make_promo_proof.py          # (re)write the PDF
    uv run python quickstarts/_scripts/make_promo_proof.py --check  # exit 1 if the checked-in PDF differs

The proof is for store S-014, promotion week 2026-W40 (Sunday 2026-10-04 to Saturday 2026-10-10). Compared with the
promotion plan (quickstarts/07-document-extraction-agent/promo_plan_2026W40.json) it carries exactly three errors:
line 1 prints $24.99 for P-0101 (plan $22.99), line 3 ends P-0141 on 2026-10-17 (plan 2026-10-10), and line 4
advertises P-0333, which is not on promotion this week. The PDF is written by hand (Helvetica, WinAnsi) so the bytes
are deterministic.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "07-document-extraction-agent" / "eval" / "artifacts" / "promo_proof_S-014_2026W40.pdf"
W, H = 792, 612  # US Letter, landscape

HEADER = "Cymbal Beauty  \xb7  Promotion signage proof"
INFO = ["Store: S-014 Cymbal Beauty Naperville   \xb7   Store group: Chicagoland",
        "Promotion week: 2026-W40  (Sunday 2026-10-04 to Saturday 2026-10-10)",
        "Proof version 3  \xb7  printed 2026-10-01  \xb7  for the signage team"]
COLUMNS = [("Line", 40), ("Product ID", 90), ("Product", 180), ("Sign type", 370), ("Promo price", 500),
           ("Starts", 590), ("Ends", 680)]
LINES = [
    ("1", "P-0101", "Lumi\xe8re Hydra Cream", "shelf talker", "$24.99", "2026-10-04", "2026-10-10"),
    ("2", "P-0420", "Noir Velvet Eau de Parfum", "locked case card", "$79.00", "2026-10-04", "2026-10-10"),
    ("3", "P-0141", "Hydra Moisturizer", "end cap sign", "$9.99", "2026-10-04", "2026-10-17"),
    ("4", "P-0333", "Glow Body Wash", "shelf talker", "$25.00", "2026-10-04", "2026-10-10"),
    ("5", "P-0231", "Lift Hair Mask", "shelf talker", "$11.00", "2026-10-04", "2026-10-10"),
]
FOOTER = "Check every sign against this proof before it goes up (SOP 04). Signs go up before opening on Sunday."


def _text(x: float, y: float, s: str, size: int = 11, font: str = "F1") -> str:
    esc = s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return f"BT /{font} {size} Tf {x} {y} Td ({esc}) Tj ET\n"


def content() -> bytes:
    c = "0.84 0.18 0.42 rg 0 552 792 60 re f\n1 1 1 rg\n" + _text(40, 574, HEADER, 22, "F2") + "0 0 0 rg\n"
    for i, line in enumerate(INFO):
        c += _text(40, 522 - i * 18, line, 12)
    top, row_h = 440, 34
    c += f"0.93 0.93 0.93 rg 30 {top} 732 {row_h} re f\n0 0 0 rg\n"
    for label, x in COLUMNS:
        c += _text(x, top + 12, label, 11, "F2")
    for r, values in enumerate(LINES):
        y = top - (r + 1) * row_h
        for (_, x), value in zip(COLUMNS, values, strict=True):
            c += _text(x, y + 12, value, 12)
    c += "0.6 0.6 0.6 RG 0.8 w\n"
    for r in range(len(LINES) + 2):
        c += f"30 {top + row_h - r * row_h} m 762 {top + row_h - r * row_h} l S\n"
    c += _text(40, 150, FOOTER, 10)
    return c.encode("cp1252")


def pdf() -> bytes:
    stream = content()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W} {H}] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>".encode(),
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        b"<< /Title (Cymbal Beauty promotion signage proof S-014 2026-W40) >>",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info 7 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    data = pdf()
    if ap.parse_args(argv).check:
        if not OUT.exists() or OUT.read_bytes() != data:
            print(f"stale: {OUT} (run make_promo_proof.py)")
            return 1
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(data)
    print("wrote", OUT.relative_to(OUT.parents[3]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

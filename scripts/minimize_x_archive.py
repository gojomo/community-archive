#!/usr/bin/env python3
"""Strip a full X/Twitter archive .zip down to what Community Archive reads.

The upload page (src/lib/upload-archive/handleFileUpload.ts) only ever opens a
handful of files under data/. This writes a new zip holding just those files,
so direct messages, media, ad data, IP logs, contacts and everything else are
not in the file you hand to the browser at all.

    python3 minimize_x_archive.py twitter-archive.zip [minimal.zip] [--no-likes]

Standard library only; makes no network connections; never modifies the input.
"""

import argparse
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

# Mirrors requiredFiles / optionalFiles in handleFileUpload.ts.
REQUIRED = ["profile", "account", "tweets", "follower", "following"]
OPTIONAL = ["note-tweet", "like", "community-tweet"]
# Large archives split these into extra files such as data/tweets-part1.js.
MULTIPART = ["tweets", "like", "following", "follower"]

WANTED = re.compile(
    r"(?:^|/)data/("
    + "|".join(re.escape(n) for n in REQUIRED + OPTIONAL)
    + r"|tweet"  # older archives name tweets.js "tweet.js"
    + r"|(?:" + "|".join(MULTIPART) + r")-part\d+"
    + r")\.js$"
)

# The only account fields the site validates. The site drops `email` in the
# browser; keeping an allowlist here also drops anything X adds later.
ACCOUNT_FIELDS = {
    "createdVia",
    "username",
    "accountId",
    "createdAt",
    "accountDisplayName",
}


def logical_name(stem):
    """'tweets-part2' -> 'tweets', 'tweet' -> 'tweets'."""
    stem = re.sub(r"-part\d+$", "", stem)
    return "tweets" if stem == "tweet" else stem


def scrub_account(raw):
    text = raw.decode("utf-8")
    start = text.index("[")
    records = json.loads(text[start:])
    for record in records:
        record["account"] = {
            k: v for k, v in record["account"].items() if k in ACCOUNT_FIELDS
        }
    body = json.dumps(records, ensure_ascii=False, indent=2)
    return (text[:start] + body).encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("archive", type=Path, help="full X archive .zip")
    parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        help="where to write the minimal zip (default: <archive>-minimal.zip)",
    )
    parser.add_argument(
        "--no-likes", action="store_true", help="also leave out your likes"
    )
    args = parser.parse_args()

    output = args.output or args.archive.with_name(
        args.archive.stem + "-minimal.zip"
    )
    if output.exists():
        sys.exit(f"Refusing to overwrite existing file: {output}")

    with zipfile.ZipFile(args.archive) as source:
        keep = {}  # output name -> source ZipInfo
        dropped = 0
        for info in source.infolist():
            match = None
            if not info.is_dir() and "__MACOSX" not in info.filename:
                match = WANTED.search(info.filename)
            if match and args.no_likes and logical_name(match.group(1)) == "like":
                match = None
            if not match:
                dropped += not info.is_dir()
                continue
            name = f"data/{match.group(1)}.js"
            if name in keep:
                sys.exit(
                    f"Two entries look like {name}: "
                    f"{keep[name].filename!r} and {info.filename!r}. "
                    "Is this more than one archive zipped together?"
                )
            keep[name] = info

        present = {logical_name(Path(n).stem) for n in keep}
        missing = [n for n in REQUIRED if n not in present]
        if missing:
            sys.exit(
                "Not a complete X archive; missing data file(s): "
                + ", ".join(f"data/{n}.js" for n in missing)
            )

        try:
            with zipfile.ZipFile(
                output, "x", compression=zipfile.ZIP_DEFLATED
            ) as target:
                for name in sorted(keep):
                    if name == "data/account.js":
                        target.writestr(name, scrub_account(source.read(keep[name])))
                    else:
                        with source.open(keep[name]) as src, target.open(
                            name, "w", force_zip64=True
                        ) as dst:
                            shutil.copyfileobj(src, dst, 1 << 20)
        except BaseException:
            output.unlink(missing_ok=True)
            raise

    with zipfile.ZipFile(output) as result:
        print(f"Wrote {output}")
        for info in result.infolist():
            print(f"  {info.file_size:>13,} bytes  {info.filename}")
        print(f"Left out {dropped:,} other files from the original archive.")


if __name__ == "__main__":
    main()

"""Verify original/repair package pairs; this does not prove visual fidelity."""
import hashlib
import json
import posixpath
import sys
import urllib.parse
import zipfile
import xml.etree.ElementTree as ET


def resolve(part, target):
    source = part.replace('/_rels/', '/').removesuffix('.rels')
    if part == '_rels/.rels':
        source = ''
    target = urllib.parse.unquote(target)
    return posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join(posixpath.dirname(source), target))


def verify(source, output, allow_parts=None):
    errors = []
    allow = set(allow_parts or [])
    with zipfile.ZipFile(source) as before, zipfile.ZipFile(output) as after:
        names, out_names = set(before.namelist()), set(after.namelist())
        if after.testzip():
            errors.append('Output ZIP failed CRC validation')
        if len(after.namelist()) != len(out_names):
            errors.append('Duplicate output entries')
        missing = names - out_names
        changed = [n for n in sorted(names & out_names) if before.read(n) != after.read(n)]
        unexpected = [n for n in changed if not (n.endswith('.rels') or n == '[Content_Types].xml' or n in allow)]
        added = out_names - names
        for n in out_names:
            if n.endswith(('.xml', '.rels')):
                try:
                    ET.fromstring(after.read(n))
                except ET.ParseError:
                    errors.append(f'Invalid XML: {n}')
            if n.endswith('.rels') and n in names:
                old = {x.get('Id'): x.attrib for x in ET.fromstring(before.read(n))}
                new = {x.get('Id'): x.attrib for x in ET.fromstring(after.read(n))}
                if old.keys() != new.keys():
                    errors.append(f'Relationship IDs changed: {n}')
                for rid in old.keys() & new.keys():
                    a, b = old[rid], new[rid]
                    target = resolve(n, b.get('Target', ''))
                    if b.get('TargetMode', '').lower() != 'external' and target not in out_names:
                        errors.append(f'Dangling relationship: {n} {rid}')
                    if a == b:
                        continue
                    attributes = dict(b)
                    attributes['Target'] = a.get('Target')
                    original = resolve(n, a.get('Target', ''))
                    if (attributes != a or a.get('TargetMode', '').lower() == 'external'
                            or posixpath.splitext(original)[1].lower() not in {'.emf', '.wmf'}
                            or target not in added or not target.endswith('.png')):
                        errors.append(f'Unexpected relationship change: {n} {rid}')
        for n in added:
            data = after.read(n)
            if not n.endswith('.png') or not data.startswith(b'\x89PNG\r\n\x1a\n'):
                errors.append(f'Unexpected or invalid generated part: {n}')
        before_ct = ET.fromstring(before.read('[Content_Types].xml'))
        after_ct = ET.fromstring(after.read('[Content_Types].xml'))
        ct_key = lambda x: (x.tag, tuple(sorted(x.attrib.items())))
        old_ct, new_ct = {ct_key(x) for x in before_ct}, {ct_key(x) for x in after_ct}
        if old_ct - new_ct:
            errors.append('Original content types changed')
        for tag, attrs in new_ct - old_ct:
            if not tag.endswith('}Default') or dict(attrs) != {'Extension': 'png', 'ContentType': 'image/png'}:
                errors.append('Unexpected content type added')
        if added and not any(x.get('Extension', '').lower() == 'png' and x.get('ContentType') == 'image/png' for x in after_ct):
            errors.append('Missing PNG content type')
        hashes = {n: hashlib.sha256(after.read(n)).hexdigest() for n in sorted(names & out_names) if n.startswith('ppt/embeddings/')}
        return {'passed': not missing and not unexpected and not errors,
                'changed_parts': changed, 'missing_parts': sorted(missing),
                'unexpected_changes': unexpected, 'errors': errors, 'ole_sha256': hashes,
                'added_parts': sorted(added)}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="Verify original/repair package pairs")
    parser.add_argument("source")
    parser.add_argument("output")
    parser.add_argument("--allow-parts", nargs="*", default=[], help="Parts permitted to change (e.g. edited OLE/previews)")
    args = parser.parse_args()
    report = verify(args.source, args.output, allow_parts=args.allow_parts)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['passed'] else 1)

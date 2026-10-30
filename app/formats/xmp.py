import re
import xml.etree.ElementTree as ET

from .base import field

NS = {
    "x": "adobe:ns:meta/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dc": "http://purl.org/dc/elements/1.1/",
    "xmp": "http://ns.adobe.com/xap/1.0/",
}
for _p, _u in NS.items():
    ET.register_namespace(_p, _u)

RDF = "{%s}" % NS["rdf"]

# key -> (prefix, local name, container kind, label)
PROPS = {
    "xmp.title": ("dc", "title", "alt", "Title (dc:title)"),
    "xmp.creator": ("dc", "creator", "seq", "Creator (dc:creator, ; separated)"),
    "xmp.description": ("dc", "description", "alt", "Description (dc:description)"),
    "xmp.rights": ("dc", "rights", "alt", "Rights (dc:rights)"),
    "xmp.subject": ("dc", "subject", "bag", "Keywords (dc:subject, comma separated)"),
    "xmp.createdate": ("xmp", "CreateDate", "simple", "Create Date (xmp:CreateDate)"),
    "xmp.creatortool": ("xmp", "CreatorTool", "simple", "Creator Tool (xmp:CreatorTool)"),
}
JOIN = {"alt": "", "seq": "; ", "bag": ", ", "simple": ""}

XMP_SCHEMA = [field(k, v[3], "XMP") for k, v in PROPS.items()]

_XPACKET_START = b'<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
_XPACKET_END = b'\n<?xpacket end="w"?>'


def _q(prefix, local):
    return "{%s}%s" % (NS[prefix], local)


def _parse(packet):
    if not packet:
        return None
    m = re.search(rb"<x:xmpmeta.*</x:xmpmeta>", packet, re.S)
    if not m:
        m = re.search(rb"<rdf:RDF.*</rdf:RDF>", packet, re.S)
    if not m:
        return None
    return ET.fromstring(m.group(0))


def _descriptions(root):
    return list(root.iter(RDF + "Description")) if root is not None else []


def read(packet):
    out = {k: "" for k in PROPS}
    try:
        root = _parse(packet)
    except ET.ParseError:
        return out
    for key, (pfx, local, kind, _) in PROPS.items():
        q = _q(pfx, local)
        for d in _descriptions(root):
            if q in d.attrib:
                out[key] = d.attrib[q]
                break
            el = d.find(q)
            if el is None:
                continue
            if kind == "simple":
                out[key] = (el.text or "").strip()
            else:
                items = [(li.text or "") for li in el.iter(RDF + "li")]
                out[key] = JOIN[kind].join(items)
            break
    return out


def apply(packet, changes):
    """Return a new packet with the xmp.* changes applied to `packet` (may be None)."""
    try:
        root = _parse(packet)
    except ET.ParseError as e:
        raise ValueError(f"existing XMP packet is not valid XML: {e}")
    if root is None:
        root = ET.Element(_q("x", "xmpmeta"))
        rdf = ET.SubElement(root, RDF + "RDF")
        ET.SubElement(rdf, RDF + "Description", {RDF + "about": ""})
    descs = _descriptions(root)
    if not descs:
        rdf = root if root.tag == RDF + "RDF" else root.find(RDF + "RDF")
        descs = [ET.SubElement(rdf, RDF + "Description", {RDF + "about": ""})]
    for key, value in changes.items():
        if key not in PROPS:
            continue
        pfx, local, kind, _ = PROPS[key]
        q = _q(pfx, local)
        for d in descs:
            d.attrib.pop(q, None)
            for el in d.findall(q):
                d.remove(el)
        if value == "":
            continue
        el = ET.SubElement(descs[0], q)
        if kind == "simple":
            el.text = value
        elif kind == "alt":
            li = ET.SubElement(ET.SubElement(el, RDF + "Alt"), RDF + "li")
            li.set("{http://www.w3.org/XML/1998/namespace}lang", "x-default")
            li.text = value
        else:
            container = ET.SubElement(el, RDF + ("Seq" if kind == "seq" else "Bag"))
            for part in value.split(";" if kind == "seq" else ","):
                if part.strip():
                    ET.SubElement(container, RDF + "li").text = part.strip()
    return _XPACKET_START + ET.tostring(root, encoding="utf-8") + _XPACKET_END

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin

HOSTED_FEED = (
    "https://contrataciondelsectorpublico.gob.es/"
    "sindicacion/sindicacion_643/licitacionesPerfilesContratanteCompleto3.atom"
)
AGGREGATED_FEED = (
    "https://contrataciondelsectorpublico.gob.es/"
    "sindicacion/sindicacion_1044/PlataformasAgregadasSinMenores.atom"
)
FEEDS = {
    "hosted": HOSTED_FEED,
    "aggregated": AGGREGATED_FEED,
}

DIRECT_FILE_RE = re.compile(
    r"\.(?:pdf|zip|docx?|xlsx?|xls|pptx?|csv|7z)(?:$|[?#])", re.I
)
PLACSP_DOCUMENT_URL_RE = re.compile(
    r"(?:GetDocumentsById|docAccCmpnt|document(?:id|download)|download)", re.I
)
DOCUMENT_REFERENCE_TAGS = {
    "LegalDocumentReference",
    "TechnicalDocumentReference",
    "AdditionalDocumentReference",
    "GeneralDocumentReference",
    "GeneralDocumentDocumentReference",
    "AdditionalPublicationDocumentReference",
}


def clean(value: object) -> str:
    return " ".join(str(value or "").split())


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def atom_child(entry: ET.Element, name: str) -> str | None:
    for child in list(entry):
        if local(child.tag) == name:
            value = clean(child.text)
            if value:
                return value
    return None


def texts(root: ET.Element, name: str) -> list[str]:
    return [clean(x.text) for x in root.iter() if local(x.tag) == name and clean(x.text)]


def first(root: ET.Element, *names: str) -> str | None:
    for name in names:
        values = texts(root, name)
        if values:
            return values[0]
    return None


def candidate_id(entry: ET.Element) -> str:
    atom_id = atom_child(entry, "id")
    folder = first(entry, "ContractFolderID", "ContractFolderStatusCode", "ID")
    raw = clean(atom_id or folder)
    if not raw:
        return ""
    return "ES-PLACSP:" + re.sub(r"[^A-Za-z0-9._:-]+", "_", raw)


def contract_folder_id(entry: ET.Element) -> str:
    return clean(first(entry, "ContractFolderID") or "")


def _http_values(root: ET.Element, base_url: str = "") -> list[str]:
    out: list[str] = []
    for node in root.iter():
        name = local(node.tag)
        if name in {"URI", "URL"} and clean(node.text):
            raw = clean(node.text)
            url = urljoin(base_url, raw) if base_url else raw
            if url.startswith(("http://", "https://")):
                out.append(url)
        href = clean(node.attrib.get("href"))
        if href:
            url = urljoin(base_url, href) if base_url else href
            if url.startswith(("http://", "https://")):
                out.append(url)
    return list(dict.fromkeys(out))


def document_urls(entry: ET.Element, base_url: str = "") -> list[str]:
    """Extract authoritative procurement-document URLs from a PLACSP Atom entry.

    PLACSP's official syndication format puts PCAP/PPT/additional documents under
    LegalDocumentReference, TechnicalDocumentReference and AdditionalDocumentReference.
    Their download URLs are commonly `GetDocumentsById` WCM routes with no filename
    extension, so extension-only filtering silently discards real tender documents.
    """
    urls: list[str] = []

    for node in entry.iter():
        node_name = local(node.tag)
        if node_name in DOCUMENT_REFERENCE_TAGS or node_name.endswith("DocumentReference"):
            urls.extend(_http_values(node, base_url))

    # Defensive compatibility for feeds where namespace/wrapper changes obscure the
    # reference parent but the canonical PLACSP download URL remains recognizable.
    for url in _http_values(entry, base_url):
        if PLACSP_DOCUMENT_URL_RE.search(url) or DIRECT_FILE_RE.search(url):
            urls.append(url)

    out: list[str] = []
    for url in urls:
        if url not in out:
            out.append(url)
    return out


def next_link(root: ET.Element, current_url: str) -> str | None:
    for node in root.iter():
        if local(node.tag) == "link" and node.attrib.get("rel") == "next":
            href = clean(node.attrib.get("href"))
            if href:
                return urljoin(current_url, href)
    return None


def entries(root: ET.Element) -> list[ET.Element]:
    return [node for node in list(root) if local(node.tag) == "entry"]

from pathlib import Path
import os, re, json, hashlib
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

URL = 'https://pmp.b2g.etat.lu/index.php?id=544016&orgAcronyme=t5y&page=Entreprise.EntrepriseDemandeTelechargementDce'
OUT = Path('dce_store/514529-2026')
OUT.mkdir(parents=True, exist_ok=True)

result = {'notice_id':'514529-2026','url':URL,'status':'STARTED','files':[],'blocker':None}

def save_download(dl):
    path = OUT / (dl.suggested_filename or 'DCE.zip')
    dl.save_as(path)
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    result['files'].append({'name':path.name,'size':path.stat().st_size,'sha256':h})

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.goto(URL, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_timeout(2500)

        # Save the live DOM for debugging every run.
        (OUT/'page.html').write_text(page.content(), encoding='utf-8')

        # Some PMP notices first expose an anonymous-download choice.
        for label in [r'Je souhaite télécharger anonymement', r'télécharger anonymement', r'telecharger anonymement']:
            try:
                loc = page.get_by_text(re.compile(label, re.I)).first
                if loc.count() and loc.is_visible():
                    loc.click(timeout=3000)
                    page.wait_for_timeout(1000)
                    break
            except Exception:
                pass

        # Fill contact fields only if such a form is actually present.
        values = {
            'nom': os.getenv('DCE_CONTACT_LAST_NAME','Procurement'),
            'prénom': os.getenv('DCE_CONTACT_FIRST_NAME','Automation'),
            'prenom': os.getenv('DCE_CONTACT_FIRST_NAME','Automation'),
            'email': os.getenv('DCE_CONTACT_EMAIL','procurement@example.com'),
            'courriel': os.getenv('DCE_CONTACT_EMAIL','procurement@example.com'),
            'raison sociale': os.getenv('DCE_COMPANY_NAME','Test'),
            'société': os.getenv('DCE_COMPANY_NAME','Test'),
            'societe': os.getenv('DCE_COMPANY_NAME','Test'),
        }
        for key,value in values.items():
            try:
                loc = page.get_by_label(re.compile(key,re.I)).first
                if loc.count() and loc.is_visible(): loc.fill(value)
            except Exception:
                pass

        downloaded = False
        errors = []

        # The real PMP control is often an anchor styled as a button.
        candidates = [
            page.get_by_text(re.compile(r'^Télécharger le Dossier de soumission$', re.I)).first,
            page.get_by_text(re.compile(r'Télécharger le Dossier de soumission', re.I)).first,
            page.get_by_role('link', name=re.compile(r'Télécharger.*Dossier', re.I)).first,
            page.locator('a').filter(has_text=re.compile(r'Télécharger.*Dossier', re.I)).first,
            page.locator('a[href]').filter(has_text=re.compile(r'Télécharger', re.I)).first,
        ]

        for loc in candidates:
            try:
                if not loc.count() or not loc.is_visible():
                    continue
                href = loc.get_attribute('href')
                # First try the browser download event.
                try:
                    with page.expect_download(timeout=15000) as info:
                        loc.click(force=True)
                    save_download(info.value)
                    downloaded = True
                    break
                except Exception as e:
                    errors.append('expect_download: '+str(e))
                    # If it is a normal href, navigate/request it directly in the same session.
                    if href and not href.lower().startswith('javascript:'):
                        target = urljoin(page.url, href)
                        resp = context.request.get(target, timeout=30000)
                        ctype = (resp.headers.get('content-type') or '').lower()
                        disp = resp.headers.get('content-disposition') or ''
                        body = resp.body()
                        if resp.ok and body and ('zip' in ctype or 'octet-stream' in ctype or 'attachment' in disp.lower()):
                            name = 'DCE.zip'
                            m = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';]+)', disp, re.I)
                            if m: name = m.group(1)
                            path = OUT/name
                            path.write_bytes(body)
                            result['files'].append({'name':path.name,'size':path.stat().st_size,'sha256':hashlib.sha256(body).hexdigest()})
                            downloaded = True
                            break
            except Exception as e:
                errors.append(str(e))

        if downloaded:
            result['status']='DOWNLOADED'
        else:
            result['status']='NO_DOWNLOAD'
            result['blocker']=' | '.join(errors[-5:]) if errors else 'No visible matching download control'
            page.screenshot(path=str(OUT/'page.png'),full_page=True)
            (OUT/'page_after.html').write_text(page.content(), encoding='utf-8')
        browser.close()
except Exception as e:
    result['status']='ERROR_RETRYABLE'
    result['blocker']=str(e)

(OUT/'manifest.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(result,indent=2,ensure_ascii=False))
if result['status'] != 'DOWNLOADED':
    raise SystemExit(2)

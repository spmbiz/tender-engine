from pathlib import Path
import os, re, json, hashlib
from playwright.sync_api import sync_playwright

URL = 'https://pmp.b2g.etat.lu/index.php?id=544016&orgAcronyme=t5y&page=Entreprise.EntrepriseDemandeTelechargementDce'
OUT = Path('dce_store/514529-2026')
OUT.mkdir(parents=True, exist_ok=True)

result = {'notice_id':'514529-2026','url':URL,'status':'STARTED','files':[],'blocker':None}
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.goto(URL, wait_until='domcontentloaded', timeout=60000)
        for label in ['Je souhaite télécharger anonymement','télécharger anonymement','telecharger anonymement','anonym']:
            try:
                page.get_by_text(re.compile(label,re.I)).first.click(timeout=2500)
                break
            except Exception:
                pass
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
                if loc.count(): loc.fill(value)
            except Exception:
                pass
        try:
            boxes = page.locator('input[type="checkbox"]')
            for i in range(min(boxes.count(),12)):
                b=boxes.nth(i)
                if b.is_visible() and b.is_enabled() and not b.is_checked(): b.check(force=True)
        except Exception:
            pass
        downloaded = False
        last_error = None
        for pattern in [r'Télécharger',r'Telecharger',r'Valider',r'Download']:
            try:
                button=page.get_by_role('button',name=re.compile(pattern,re.I)).first
                with page.expect_download(timeout=20000) as info:
                    button.click(force=True)
                dl=info.value
                path=OUT/(dl.suggested_filename or 'DCE.zip')
                dl.save_as(path)
                h=hashlib.sha256(path.read_bytes()).hexdigest()
                result['files'].append({'name':path.name,'size':path.stat().st_size,'sha256':h})
                downloaded=True
                break
            except Exception as e:
                last_error=str(e)
        if downloaded:
            result['status']='DOWNLOADED'
        else:
            result['status']='NO_DOWNLOAD'
            result['blocker']=last_error
            page.screenshot(path=str(OUT/'page.png'),full_page=True)
        browser.close()
except Exception as e:
    result['status']='ERROR_RETRYABLE'
    result['blocker']=str(e)

(OUT/'manifest.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(result,indent=2,ensure_ascii=False))
if result['status'] != 'DOWNLOADED':
    raise SystemExit(2)

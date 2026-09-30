"""Local-only sandbox launcher. Credentials stay in process memory."""
import getpass
import os

os.environ.update(
    APIC_URL='https://sandboxapicdc.cisco.com',
    APIC_USER='admin', APIC_VERIFY='false', PYTHON_DOTENV_DISABLED='1',
    APIC_TIMEOUT_SEC='15', APIC_MAX_RETRY='1',
)
if not os.environ.get('APIC_PASS'):
    os.environ['APIC_PASS'] = getpass.getpass('Senha do sandbox Cisco: ')

from app import app


@app.after_request
def identify_lab(response):
    if response.mimetype == 'text/html' and response.status_code == 200:
        banner = '''<aside style="position:relative;z-index:10;padding:12px 20px;
        background:#17345c;color:#fff;font:14px/1.5 system-ui;text-align:center">
        <strong>LABORATÓRIO · Cisco Sandbox</strong> — dados reais do sandbox compartilhado.
        Estatísticas e associações podem estar incompletas.
        <a href="/" style="color:#fff;text-decoration:underline">Início</a> ·
        <a href="/portchannel_overview" style="color:#fff;text-decoration:underline">PC/vPC</a> ·
        <a href="/endpoint_lookup" style="color:#fff;text-decoration:underline">Localizar endpoint</a>
        </aside>'''
        response.set_data(response.get_data(as_text=True).replace('<main>', '<main>' + banner, 1) if '<main>' in response.get_data(as_text=True) else response.get_data(as_text=True).replace('<body>', '<body>' + banner, 1))
    return response


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8000, debug=False, use_reloader=False)

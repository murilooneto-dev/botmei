"""
Bot DAS-SIMEI — lógica de automação
Pode ser chamado via CLI (main) ou pelo app web (executar)
"""

import os
import random
import re
import smtplib
import time
import urllib.request
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

try:
    from playwright_stealth import stealth_sync
except ImportError:
    try:
        from playwright_stealth import Stealth
        def stealth_sync(page):
            Stealth().apply_stealth_sync(page)
    except Exception:
        def stealth_sync(page):
            pass

load_dotenv()

URL_PGMEI = "https://www8.receita.fazenda.gov.br/SimplesNacional/Aplicacoes/ATSPO/pgmei.app/Identificacao"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]

MESES_PT = ["Janeiro","Fevereiro","Março","Abril","Maio","Junho",
            "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]

# Função de log global (substituída pelo app web quando necessário)
_log_func = print

def set_log_func(func):
    global _log_func
    _log_func = func

def log(msg):
    _log_func(msg)


# ── Utilitários ───────────────────────────────────────────────────────────────

def limpar_cnpj(cnpj: str) -> str:
    return re.sub(r"\D", "", cnpj)

def pasta_empresa(cnpj: str, pasta_base: Path) -> Path:
    pasta = pasta_base / limpar_cnpj(cnpj)
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta

def data_vencimento_das() -> str:
    """Vencimento = dia 20 do mês corrente (competência = mês anterior)."""
    hoje = datetime.now()
    venc = datetime(hoje.year, hoje.month, 20)
    if venc.weekday() == 5:   # sábado → sexta
        venc = venc.replace(day=18)
    elif venc.weekday() == 6: # domingo → sexta
        venc = venc.replace(day=19)
    return venc.strftime("%d/%m/%Y")

def espera_humana(minimo=0.8, maximo=2.5):
    time.sleep(random.uniform(minimo, maximo))

def digitar_como_humano(page, elemento, texto: str):
    elemento.click()
    espera_humana(0.2, 0.5)
    elemento.fill("")
    for char in texto:
        elemento.type(char, delay=random.randint(60, 180))
    espera_humana(0.2, 0.5)

def mover_mouse_aleatoriamente(page):
    for _ in range(random.randint(2, 4)):
        page.mouse.move(random.randint(100, 900), random.randint(100, 600))
        time.sleep(random.uniform(0.1, 0.3))


# ── Detecção de elementos ─────────────────────────────────────────────────────

def encontrar_input_cnpj(page):
    for sel in [
        "input[id='cnpj']", "input[name='cnpj']",
        "input[id*='cnpj' i]", "input[name*='cnpj' i]",
        "input[placeholder*='CNPJ' i]",
        "input[maxlength='14']", "input[maxlength='18']",
        "input[type='text']:visible",
    ]:
        try:
            el = page.locator(sel).first
            if el.count() > 0:
                el.wait_for(state="visible", timeout=3000)
                return el
        except Exception:
            continue
    return None

def encontrar_botao(page, textos: list):
    for texto in textos:
        for sel in [
            f"button:has-text('{texto}')",
            f"input[value='{texto}']",
            f"input[value*='{texto}']",
            f"a:has-text('{texto}')",
        ]:
            try:
                el = page.locator(sel).first
                if el.count() > 0:
                    el.wait_for(state="visible", timeout=3000)
                    return el
            except Exception:
                continue
    return None

def verificar_e_resolver_captcha(page):
    try:
        if page.locator("iframe[src*='hcaptcha'], div.h-captcha, [data-sitekey]").count() > 0:
            log("  ⏳ Captcha invisível detectado, aguardando validação automática...")
            espera_humana(3, 5)
    except Exception:
        pass

def diagnosticar_pagina(page, etapa: str):
    try:
        path = Path(f"debug_{etapa}_{int(time.time())}.png")
        page.screenshot(path=str(path))
        log(f"  📸 Screenshot salvo: {path}")
    except Exception:
        pass


# ── Download do DAS ───────────────────────────────────────────────────────────

def baixar_das(page, cnpj: str, pasta: Path) -> Path | None:
    cnpj_limpo = limpar_cnpj(cnpj)
    hoje = datetime.now()
    mes_competencia = 12 if hoje.month == 1 else hoje.month - 1
    ano_competencia = hoje.year - 1 if hoje.month == 1 else hoje.year
    nome_mes = MESES_PT[mes_competencia - 1]
    texto_mes = f"{nome_mes}/{ano_competencia}"
    data_venc = data_vencimento_das()

    log(f"  → Competência: {texto_mes} | Vencimento: {data_venc}")

    # ETAPA 1 — Carregar portal
    try:
        page.goto(URL_PGMEI, wait_until="domcontentloaded", timeout=30000)
        espera_humana(2, 4)
    except PlaywrightTimeout:
        log("  ✗ Timeout ao carregar o portal.")
        return None

    mover_mouse_aleatoriamente(page)
    verificar_e_resolver_captcha(page)

    # ETAPA 2 — Preencher CNPJ
    campo_cnpj = encontrar_input_cnpj(page)
    if not campo_cnpj:
        log("  ✗ Campo CNPJ não encontrado.")
        diagnosticar_pagina(page, "sem_campo_cnpj")
        return None

    digitar_como_humano(page, campo_cnpj, cnpj_limpo)
    mover_mouse_aleatoriamente(page)

    btn = encontrar_botao(page, ["Continuar", "Consultar", "Avançar"])
    if not btn:
        log("  ✗ Botão Continuar não encontrado.")
        diagnosticar_pagina(page, "sem_botao_continuar")
        return None

    espera_humana(0.5, 1.5)
    btn.click()
    page.wait_for_load_state("domcontentloaded", timeout=15000)
    espera_humana(2, 3)
    verificar_e_resolver_captcha(page)

    # ETAPA 3 — Clicar em Emitir DAS
    btn_das = encontrar_botao(page, ["Emitir DAS", "Gerar DAS", "DAS-SIMEI", "Emitir Guia"])
    if not btn_das:
        log("  ✗ Link Emitir DAS não encontrado.")
        diagnosticar_pagina(page, "sem_link_emitir_das")
        return None

    espera_humana(0.5, 1.0)
    btn_das.click()
    page.wait_for_load_state("domcontentloaded", timeout=15000)
    espera_humana(2, 3)

    # ETAPA 4 — Selecionar Ano-Calendário
    log(f"  → Selecionando ano-calendário: {ano_competencia}")
    selecionou_ano = False
    try:
        for sel in ["select[id*='ano' i]", "select[name*='ano' i]", "select[id*='year' i]"]:
            el = page.locator(sel).first
            if el.count() > 0:
                el.wait_for(state="visible", timeout=5000)
                el.select_option(value=str(ano_competencia))
                espera_humana(0.8, 1.5)
                selecionou_ano = True
                log(f"  ✓ Ano {ano_competencia} selecionado.")
                break
        if not selecionou_ano:
            diagnosticar_pagina(page, "sem_seletor_ano")
        else:
            espera_humana(0.5, 1.0)
            btn_ok = encontrar_botao(page, ["Ok", "OK", "Confirmar", "Continuar"])
            if btn_ok:
                btn_ok.click()
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                espera_humana(2, 3)
                log("  ✓ Clicou em OK.")
            else:
                log("  ! Botão OK não encontrado.")
                diagnosticar_pagina(page, "sem_botao_ok_ano")
    except Exception as e:
        log(f"  ! Erro ao selecionar ano: {e}")

    # ETAPA 5 — Marcar checkbox do mês anterior
    log(f"  → Marcando checkbox de '{texto_mes}'...")
    try:
        linha = page.locator(f"tr:has-text('{texto_mes}')").first
        linha.wait_for(state="visible", timeout=10000)
        checkbox = linha.locator("input[type='checkbox']").first
        if not checkbox.is_checked():
            checkbox.check()
        espera_humana(0.5, 1.0)
        log(f"  ✓ Checkbox de '{texto_mes}' marcado.")

        # Lê Data de Vencimento direto da linha
        for celula in linha.locator("td").all():
            txt = celula.inner_text().strip()
            if re.match(r"\d{2}/\d{2}/\d{4}", txt):
                data_venc = txt
                log(f"  ✓ Data de vencimento lida da página: {data_venc}")
                break
    except Exception as e:
        log(f"  ! Erro ao marcar checkbox: {e}")
        diagnosticar_pagina(page, "sem_checkbox_mes")

    # ETAPA 6 — Preencher data de pagamento
    log(f"  → Preenchendo data de pagamento: {data_venc}")
    try:
        campo_data = page.locator(
            "input[id*='dtPagamento' i], input[id*='dataPagamento' i], "
            "input[id*='acolhimento' i], input[id*='pagamento' i]"
        ).first
        if campo_data.count() == 0:
            campo_data = page.locator("input[type='text']:visible").last
        campo_data.wait_for(state="visible", timeout=5000)
        campo_data.triple_click()
        espera_humana(0.2, 0.4)
        digitar_como_humano(page, campo_data, data_venc)
        log(f"  ✓ Data preenchida: {data_venc}")
    except Exception as e:
        log(f"  ! Erro ao preencher data: {e}")
        diagnosticar_pagina(page, "sem_campo_data")

    # ETAPA 7 — Clicar Gerar DAS
    log("  → Clicando em Gerar DAS...")
    btn_gerar = encontrar_botao(page, ["Gerar DAS","Apurar/Gerar DAS","Apurar","Gerar","Emitir DAS","Emitir"])
    if not btn_gerar:
        try:
            for btn in page.locator("input[type='button']:visible, input[type='submit']:visible, button:visible").all():
                txt = (btn.get_attribute("value") or btn.inner_text() or "").strip()
                if txt and "Atualizar" not in txt and "Pagar" not in txt and "Online" not in txt:
                    btn_gerar = btn
                    break
        except Exception:
            pass
    if not btn_gerar:
        log("  ✗ Botão Gerar DAS não encontrado.")
        diagnosticar_pagina(page, "sem_botao_gerar")
        return None

    nome_arquivo = f"DAS_{cnpj_limpo}_{ano_competencia}{mes_competencia:02d}.pdf"
    caminho_arquivo = pasta / nome_arquivo

    espera_humana(0.5, 1.0)
    btn_gerar.click()
    page.wait_for_load_state("domcontentloaded", timeout=20000)
    espera_humana(2, 3)

    # ETAPA 8 — Clicar Imprimir/Visualizar PDF e baixar
    log("  → Procurando botão Imprimir/Visualizar PDF...")
    btn_pdf = encontrar_botao(page, [
        "Imprimir/Visualizar PDF","Imprimir / Visualizar PDF",
        "Visualizar PDF","Imprimir PDF","Imprimir","PDF"
    ])
    if not btn_pdf:
        log("  ✗ Botão PDF não encontrado.")
        diagnosticar_pagina(page, "sem_botao_pdf")
        return None

    try:
        with page.expect_download(timeout=30000) as dl_info:
            btn_pdf.click()
        dl_info.value.save_as(str(caminho_arquivo))
        log(f"  ✓ DAS salvo em: {caminho_arquivo}")
        return caminho_arquivo
    except Exception:
        pass

    # Fallback: PDF abriu em nova aba
    try:
        espera_humana(2, 3)
        paginas = page.context.pages
        aba_pdf = paginas[-1] if len(paginas) > 1 else page
        url_pdf = aba_pdf.url
        log(f"  → PDF em nova aba: {url_pdf}")
        if "pdf" in url_pdf.lower():
            cookies = page.context.cookies()
            cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
            req = urllib.request.Request(url_pdf, headers={
                "Cookie": cookie_str,
                "User-Agent": page.evaluate("navigator.userAgent"),
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                caminho_arquivo.write_bytes(resp.read())
        else:
            aba_pdf.pdf(path=str(caminho_arquivo))
        log(f"  ✓ DAS salvo em: {caminho_arquivo}")
        if len(paginas) > 1:
            aba_pdf.close()
        return caminho_arquivo
    except Exception as e:
        log(f"  ✗ Erro ao salvar PDF: {e}")
        diagnosticar_pagina(page, "erro_salvar_pdf")
        return None


# ── Envio de email ────────────────────────────────────────────────────────────

def enviar_email(destinatario: str, nome_empresa: str, cnpj: str, arquivo: Path):
    remetente = os.getenv("EMAIL_REMETENTE")
    senha = os.getenv("EMAIL_SENHA_APP")
    if not remetente or not senha:
        log("  ✗ Credenciais de email não configuradas no .env")
        return

    hoje = datetime.now()
    competencia = f"12/{hoje.year-1}" if hoje.month == 1 else f"{hoje.month-1:02d}/{hoje.year}"
    assunto = f"DAS-SIMEI {competencia} – {nome_empresa}"

    msg = MIMEMultipart("related")
    msg["From"] = remetente
    msg["To"] = destinatario
    msg["Subject"] = assunto

    alternativa = MIMEMultipart("alternative")
    msg.attach(alternativa)

    corpo_texto = (
        f"Olá,\n\nSegue em anexo o DAS-SIMEI referente à competência {competencia} "
        f"da empresa {nome_empresa} (CNPJ: {cnpj}).\n\nAtenciosamente,\nTesserato Contabilidade"
    )
    alternativa.attach(MIMEText(corpo_texto, "plain", "utf-8"))

    assinatura_path = Path(__file__).parent / "assinatura.png"
    tem_assinatura = assinatura_path.exists()
    img_tag = '<img src="cid:assinatura" alt="Assinatura" style="max-width:580px; display:block;">' if tem_assinatura else ""

    corpo_html = f"""<html><body style="font-family:Arial,sans-serif;font-size:14px;color:#333;margin:0;padding:20px;">
      <p>Olá,</p>
      <p>Segue em anexo o <strong>DAS-SIMEI</strong> referente à competência
         <strong>{competencia}</strong> da empresa <strong>{nome_empresa}</strong>
         (CNPJ: {cnpj}).</p>
      <br>
      <p>Atenciosamente,</p>
      {img_tag}
    </body></html>"""
    alternativa.attach(MIMEText(corpo_html, "html", "utf-8"))

    if tem_assinatura:
        with open(assinatura_path, "rb") as f:
            img = MIMEBase("image", "png")
            img.set_payload(f.read())
        encoders.encode_base64(img)
        img.add_header("Content-ID", "<assinatura>")
        img.add_header("Content-Disposition", "inline", filename="assinatura.png")
        msg.attach(img)

    with open(arquivo, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{arquivo.name}"')
    msg.attach(part)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(remetente, senha)
            s.sendmail(remetente, destinatario, msg.as_string())
        log(f"  ✓ Email enviado para {destinatario}")
    except Exception as e:
        log(f"  ✗ Falha ao enviar email: {e}")


# ── Execução principal ────────────────────────────────────────────────────────

def executar(empresas: list, pasta_downloads: Path, log_callback=None, parar_flag=None):
    """
    Chamado pelo app web ou pelo CLI.
    empresas: lista de dicts com cnpj, nome, email
    pasta_downloads: Path onde salvar os PDFs
    log_callback: função chamada com cada mensagem de log
    parar_flag: lista [False] — se virar [True], interrompe o loop
    """
    if log_callback:
        set_log_func(log_callback)

    pasta_downloads = Path(pasta_downloads)
    pasta_downloads.mkdir(parents=True, exist_ok=True)

    hoje = datetime.now()
    mes = 12 if hoje.month == 1 else hoje.month - 1
    ano = hoje.year - 1 if hoje.month == 1 else hoje.year
    competencia = f"{mes:02d}/{ano}"

    log(f"{'='*60}")
    log(f"Bot DAS-SIMEI | Competência: {competencia}")
    log(f"Processando {len(empresas)} empresa(s)...")
    log(f"{'='*60}")

    with sync_playwright() as p:
        browser = p.firefox.launch(headless=False)
        context = browser.new_context(
            accept_downloads=True,
            viewport={"width": random.randint(1280, 1920), "height": random.randint(800, 1080)},
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
        )
        page = context.new_page()
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR','pt','en-US'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3] });
        """)

        for i, empresa in enumerate(empresas, 1):
            if parar_flag and parar_flag[0]:
                log("⛔ Processo interrompido pelo usuário.")
                break

            cnpj  = empresa.get("cnpj", "")
            nome  = empresa.get("nome", cnpj)
            email = empresa.get("email") or os.getenv("EMAIL_DESTINATARIO", "")

            log(f"\n[{i}/{len(empresas)}] {nome} — CNPJ: {cnpj}")

            try:
                pasta = pasta_empresa(cnpj, pasta_downloads)
                arquivo = baixar_das(page, cnpj, pasta)

                if arquivo and arquivo.exists():
                    log(f"  ✓ PDF gerado com sucesso.")
                    if email:
                        enviar_email(email, nome, cnpj, arquivo)
                    else:
                        log("  ! Sem email configurado para esta empresa.")
                else:
                    log(f"  ✗ Falha ao gerar DAS para {cnpj}.")
            except Exception as e:
                log(f"  ✗ Erro inesperado: {e}")

            if i < len(empresas):
                espera_humana(2, 4)

        browser.close()

    log(f"\n{'='*60}")
    log(f"✅ Concluído! Arquivos em: {pasta_downloads.resolve()}")
    log(f"{'='*60}")


if __name__ == "__main__":
    import json
    p = Path("empresas.json")
    if p.exists():
        empresas = json.loads(p.read_text(encoding="utf-8"))
        executar(empresas, Path("DAS"))
    else:
        print("empresas.json não encontrado.")

# CISCO-ACI — Painel de consultas

Aplicação web em Python e Flask para consultar um fabric Cisco ACI pela API REST do APIC. O painel permite que a equipe localize servidores, consulte portas e políticas e investigue eventos sem navegar diretamente pela interface do controlador.

O sistema consulta os dados do APIC e não oferece ações para alterar a configuração do fabric. As credenciais do controlador ficam no servidor, em variáveis de ambiente ou no arquivo `.env`.

## Imagens do painel

<img width="1427" height="883" alt="image" src="https://github.com/user-attachments/assets/49c0225c-71bb-4815-a780-ab31941291d3" />

<img width="1596" height="682" alt="image" src="https://github.com/user-attachments/assets/90faca6d-b26d-4f99-a12d-0198ec77cecc" />

<img width="1392" height="647" alt="image" src="https://github.com/user-attachments/assets/2e0f6028-7a3d-4e55-8b7e-0e52303e5035" />

<img width="1293" height="758" alt="image" src="https://github.com/user-attachments/assets/5ec9c617-145a-49ef-bf22-1d385104f93f" />

<img width="1286" height="652" alt="image" src="https://github.com/user-attachments/assets/c9e581ce-65a8-4f6f-9ad1-1dc1c2fabeb3" />

## Funcionalidades

- Busca de endpoints por IP, MAC ou parte do nome/descrição.
- Interfaces físicas com estado administrativo, estado operacional e velocidade.
- Detalhamento de portas e estatísticas de tráfego disponíveis no APIC.
- Consolidação de port-channels e vPCs por grupo lógico.
- Consulta de Access Policy Groups, AEPs, políticas e seletores.
- Seleção dinâmica de tenants e L3Outs para consultar prefixos de External EPG.
- Relatórios de VRFs, contratos, EPGs e Bridge Domains, incluindo subnets.
- Inventário do fabric, faults, eventos e auditoria de alterações.
- Filtros, exportação CSV nos relatórios compatíveis e temas claro/escuro.

## Requisitos

- Python 3.10 ou superior; desenvolvimento local validado com Python 3.14.
- Git para clonar o projeto.
- Acesso HTTPS do servidor da aplicação ao APIC.
- Conta APIC com permissões de consulta aos objetos desejados.

As dependências estão em [requirements.txt](requirements.txt). Não é necessário Node.js nem compilar o frontend.

## Instalação

### Windows — PowerShell

```powershell
git clone https://github.com/abcdanilo/CISCO-ACI.git
cd CISCO-ACI
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

### Linux

```bash
git clone https://github.com/abcdanilo/CISCO-ACI.git
cd CISCO-ACI
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Copie o exemplo somente na primeira instalação. Se já existe um `.env`, preserve sua configuração. Os comandos usam diretamente o Python do ambiente virtual, sem exigir ativação.

## Configuração

Edite o `.env` na raiz do projeto:

```dotenv
APIC_URL=https://apic.exemplo.com.br
APIC_USER=usuario_de_consulta
APIC_PASS=preencha_localmente
APIC_VERIFY=true
```

Os valores acima são exemplos. Não publique credenciais reais. O `.gitignore` exclui `.env`, ambientes virtuais, certificados, logs e backups ZIP. O `.env.example` é publicado sem credenciais.

| Variável | Finalidade | Padrão no código |
| --- | --- | --- |
| `APIC_URL` | URL base do controlador | `https://apic.exemplo.com.br`; substitua |
| `APIC_USER` | Usuário APIC | Obrigatório |
| `APIC_PASS` | Senha APIC | Obrigatório |
| `APIC_VERIFY` | Validação TLS: `true`, `false` ou caminho da CA | `False`; o exemplo usa `true` |
| `APIC_TOKEN_TTL_SEC` | Intervalo do controle local de renovação do token, em segundos | `300` |
| `DATA_CACHE_TTL_SEC` | Validade do cache de dados, em segundos | `60` |
| `APIC_PAGE_SIZE` | Tamanho de página nas consultas paginadas ao APIC | `1000` |
| `APIC_MAX_RETRY` | Limite configurado para tentativas de consulta | `3` |
| `APIC_TIMEOUT_SEC` | Timeout das requisições ao APIC, em segundos | `20` |
| `PORT` | Porta na execução direta de `app.py` | `8000` |

Variáveis do processo têm precedência sobre o `.env`. Para validar o certificado do controlador, use `APIC_VERIFY=true` ou o caminho da CA do ambiente.

## Execução

### Teste local com seu APIC

Windows:

```powershell
.\.venv\Scripts\python.exe -m flask --app app run --host 127.0.0.1 --port 8000
```

Linux:

```bash
.venv/bin/python -m flask --app app run --host 127.0.0.1 --port 8000
```

Abra [http://127.0.0.1:8000](http://127.0.0.1:8000). Mantenha o terminal aberto; **Ctrl+C** encerra a aplicação.

Esses comandos fixam a porta em 8000. A execução direta de `app.py` usa `PORT` e escuta em `0.0.0.0`, aceitando conexões pelas interfaces de rede do servidor.

### Laboratório Cisco Sandbox

```powershell
.\.venv\Scripts\python.exe -B run_sandbox.py
```

No Linux, use `.venv/bin/python -B run_sandbox.py`.

O launcher aponta para `https://sandboxapicdc.cisco.com`, usa o usuário `admin` e solicita a senha no terminal. Não há senha cadastrada no código. Se `APIC_PASS` já estiver no ambiente do processo, ela será usada sem nova solicitação; use um terminal sem credenciais de produção.

O laboratório escuta em `127.0.0.1:8000`, desativa a leitura do `.env` e a validação TLS e identifica as páginas com um banner. Sua disponibilidade e seus dados dependem do sandbox compartilhado. Não use esse launcher para conectar à APIC de produção.

### Produção

O objeto WSGI é `app:app`. Utilize o serviço WSGI e o proxy configurados no servidor. O servidor embutido do Flask (`python app.py` ou `flask run`) é destinado ao desenvolvimento.

O painel **não possui login próprio de usuários**. As credenciais APIC do servidor não restringem quem acessa o painel. Disponibilize-o em rede interna com acesso controlado ou proteja-o no proxy conforme as regras do ambiente.

## Como usar

### Página inicial

Os indicadores mostram switches, interfaces, endpoints e faults, com horários individuais de coleta. Os números não são uma fotografia simultânea de todo o fabric. Os cards organizam as telas em Interfaces, Endpoints, Conectividade L3Out, Políticas & Fabric e Operacional.

### Localizar um servidor

1. Em **Endpoints**, abra **Localizar servidor**.
2. Escolha IP/MAC exato ou nome/descrição e faça a busca.
3. Confira tenant, EPG, encapsulamento e caminhos retornados.
4. Abra uma interface identificada para consultar estado, velocidade e tráfego.

A busca por nome é parcial e ignora maiúsculas, usando os campos disponíveis no endpoint. Não consulta DNS ou CMDB. Quando não houver nome cadastrado no APIC, use IP ou MAC. Endpoints com endereços iguais em contextos diferentes permanecem separados.

### Interfaces e grupos de portas

- **Todas as Interfaces:** inclui interfaces administrativamente habilitadas e desabilitadas, separando estado administrativo de operacional.
- **Detalhamento e Tráfego:** recebe pod, node e interface ou o DN de uma porta. Mostra as últimas estatísticas disponíveis de cinco minutos, não tráfego em tempo real. Ausência de amostra não significa tráfego zero.
- **VPC Ports:** reúne os lados de um grupo lógico, mantendo port-channel, estado e membros por node. Os números de port-channel podem ser diferentes entre os peers.
- **ACC Ports:** mostra status, Policy Group, caminho físico, velocidade e configuração. Clique no grupo para consultar políticas e seletores.
- **AEP — Interfaces Físicas:** relaciona AEPs, grupos de políticas e portas identificadas.

A visão vPC distingue associação confirmada por membros físicos de correlação por nome exato + pod/node do caminho lógico. Correlações ficam sinalizadas e ambiguidades não são forçadas. “Parcial” descreve o mapeamento, não a saúde do protocolo vPC. O localizador de servidores usa somente associações físicas confirmadas para apresentar membros de bundles.

### L3Out e Bridge Domains

Em **Consultar L3Out**, selecione tenant e L3Out e refine a busca. As opções vêm do APIC e podem incluir grupos sem prefixos.

A tela apresenta **prefixos de External EPG (`l3extSubnet`)**. Não representa uma tabela de rotas estáticas ou aprendidas por protocolos de roteamento.

Em **Bridge Domains**, a coluna **Subnets (IP/prefixo)** mostra os endereços IPv4/IPv6 cadastrados diretamente no BD, preservando o endereço e o prefixo configurados. É possível pesquisar por subnet. BDs sem esses objetos são identificados; subnets de EPGs não são apresentadas como subnets do BD.

### Faults e histórico

Em **Operacional**, abra **Faults Ativos** para consultar falhas e filtrar por severidade e contexto. O relatório pode incluir severidade `cleared`; o indicador total informa essa inclusão.

**Histórico de eventos** permite selecionar eventos ou alterações de configuração, período e texto. O período inicial é de 24 horas, com limite de 31 dias por consulta e 50 registros por página. O filtro opcional de DN corresponde ao objeto afetado exato.

O histórico depende da retenção no APIC. Não há armazenamento histórico local nem comparação completa de configuração antes/depois. Fichas de interfaces e Policy Groups também oferecem falhas relacionadas e acesso ao histórico do objeto.

### Atualização, filtros e CSV

O botão **Atualizar dados** renova o relatório e as consultas dependentes. O cache fica em memória no processo; não há banco de dados local. Avisos diferenciam consultas parciais de ausência de registros. Os campos disponíveis dependem dos dados, permissões e versão do APIC.

| Exportação | Conteúdo |
| --- | --- |
| Relatórios gerais, como interfaces, BDs e endpoints | Relatório completo, independentemente dos filtros locais da tabela |
| Localizar servidor | Resultados da busca atual; detalhes operacionais adicionais das portas ficam na tela |
| VPC Ports / visão consolidada | Todos os grupos filtrados, com uma linha por membro e indicação da associação |
| Seleção de L3Out | Todos os registros da seleção e busca, além da página visível |

Os CSVs têm proteção contra interpretação de células como fórmulas. Se o cache expirar antes do download, a exportação pode refletir uma coleta mais recente que a tela.

## Organização do projeto

| Arquivo ou pasta | Responsabilidade |
| --- | --- |
| `app.py` | Configuração Flask, sessão APIC, paginação, cache, relatórios gerais e CSV |
| `aci_diagnostics.py` | Localização de endpoints, interface e utilitário de proteção CSV |
| `aci_portchannels.py` | Consolidação PC/vPC, evidências, filtros e CSV |
| `aci_access.py` | Políticas, relações e seletores de grupos de acesso |
| `aci_l3out.py` | Inventário dinâmico de tenants/L3Outs e seleção de prefixos |
| `aci_history.py` | Consultas paginadas de eventos e auditoria |
| `run_sandbox.py` | Inicialização exclusiva do laboratório Cisco |
| `templates/` | Páginas HTML e templates Jinja |
| `static/` | CSS e JavaScript das telas, filtros, indicadores e temas |
| `tests/` | Testes com respostas simuladas, sem APIC real |
| `.env.example` | Modelo de configuração sem credenciais |
| `requirements.txt` | Dependências Python |
| `AGENTS.md` | Instruções locais de manutenção assistida; não configura a execução |

`static/theme.js` e `static/theme.css` controlam os temas. `static/report-tools.js` reúne ferramentas comuns dos relatórios. Os demais scripts acompanham funcionalidades como histórico, diagnósticos, L3Out e port-channels.

## Catálogo dos templates

| Template | Página / rota | Finalidade |
| --- | --- | --- |
| `home.html` | `/` | Indicadores e navegação |
| `report_interfaces_up_full.html` | `/interfaces/up_full` | Todas as interfaces físicas |
| `interface_details.html` | `/interface_details` | Ficha da interface, velocidades, tráfego e falhas |
| `portchannel_overview.html` | `/portchannels` e `/portchannel_overview` | Visão consolidada usada em VPC Ports |
| `report_acc_ports.html` | `/acc_ports` | Access Policy Groups e portas |
| `access_group.html` | `/access_group?dn=...` | Políticas e seletores do grupo de acesso |
| `report_aep_interfaces.html` | `/aep_interfaces` | AEPs e interfaces físicas |
| `endpoint_lookup.html` | `/endpoint_lookup` | Busca de servidor por endereço ou nome |
| `report_endpoints.html` | `/endpoints` | Inventário de endpoints |
| `report_vmware.html` | `/vmware` | Inventário VMware disponível no APIC |
| `report_ip_endpoints.html` | `/ip_endpoints` | Endpoints por IP e contexto |
| `l3out_explorer.html` | `/l3out_explorer` | Tenant/L3Out e prefixos de External EPG |
| `report_vrfs.html` | `/vrfs` | VRFs |
| `report_contracts.html` | `/contracts` | Contratos |
| `report_epgs.html` | `/epgs` | Endpoint Groups |
| `report_bds.html` | `/bds` | Bridge Domains e subnets diretamente associadas |
| `report_faults.html` | `/faults` | Faults, severidade e contexto |
| `report_fabric_nodes.html` | `/fabric_nodes` | Inventário de nodes do fabric |
| `history.html` | `/history` | Eventos e auditoria de alterações |
| `diagnostics_base.html` | Sem rota própria | Estrutura compartilhada das telas de diagnóstico |
| `report_up.html` | `/up`, fora do menu principal | Relatório de interfaces ativas mantido por compatibilidade |
| `report_down.html` | `/down`, fora do menu principal | Relatório de interfaces inativas mantido por compatibilidade |
| `report_portchannels.html` | Sem rota HTML ativa | Template antigo por switch; `/portchannels` usa a visão consolidada |

As páginas antigas de L3Out e `/l3out` redirecionam ao explorador dinâmico. Não é necessário criar rotas fixas para novos tenants.

## APIs e metadados

As telas consomem rotas locais `/api/...`; o navegador não precisa receber as credenciais APIC. Exemplos:

| Rota | Uso |
| --- | --- |
| `/api/bds` | Bridge Domains e subnets |
| `/api/endpoint_lookup?q=192.0.2.10` | Endpoint por IP exato |
| `/api/endpoint_lookup?mode=name&q=servidor` | Endpoint por nome parcial |
| `/api/interface_details?dn=...` | Interface por DN físico |
| `/api/portchannel_overview` | Grupos PC/vPC |
| `/api/l3out_inventory` | Inventário dinâmico L3Out |
| `/api/history?kind=audit` | Auditoria do período padrão |
| `/api/object_faults?dn=...` | Falhas relacionadas ao objeto |

Relatórios gerais retornam listas JSON; diagnósticos e inventários compostos podem retornar objetos. Consulte a implementação da rota antes de consumir seu resultado. Quando aplicáveis, `X-Collected-At`, `X-Data-Cache` e `X-Collection-Warnings` informam coleta, cache e avisos. `?refresh=1` renova consultas que utilizam o cache compartilhado.

## Atualização e reinício

Preserve o `.env` e confira alterações locais com `git status`. Em uma instalação sem mudanças pendentes:

```bash
git pull --ff-only
```

Atualize as dependências com o Python da `.venv` e `-m pip install -r requirements.txt`. Se a atualização for por cópia, leve `app.py`, todos os módulos `aci_*.py`, `templates/`, `static/` e `requirements.txt` juntos. Não copie a `.venv` de outra máquina.

No laboratório, pressione **Ctrl+C** e execute novamente o launcher. Em produção, reinicie o serviço que hospeda `app:app`. Depois atualize o navegador com **Ctrl+F5**.

O laboratório não usa recarga automática. **Ctrl+F5 sozinho não reinicia o Python nem limpa os templates em memória no servidor.**

## Solução de problemas

| Sintoma | Verificar |
| --- | --- |
| Página não abre | Processo ativo, porta e endereço; `127.0.0.1` acessa somente a própria máquina |
| Porta 8000 em uso | Outra instância ativa; encerre o processo correto antes de iniciar novamente |
| `APIC_USER e APIC_PASS devem estar definidos` | Variáveis obrigatórias, `.env` e ambiente do processo |
| Página abre, mas dados falham | URL APIC, rede, credenciais, permissões, certificado e erro no terminal |
| Erro de certificado | CA confiável e `APIC_VERIFY` |
| Menu antigo após Ctrl+F5 | Reinício da aplicação e diretório usado para iniciá-la |
| vPC parcial ou não associado | Deployment e evidências por node nos detalhes do grupo |
| Tráfego indisponível | Existência e horário das amostras de cinco minutos |
| Histórico vazio | Tipo, período, filtros e retenção do APIC |

Ao relatar problemas, inclua tela, horário, mensagem de erro e contexto necessário, omitindo senhas, tokens e informações sensíveis.

## Testes

Windows:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
```

Linux:

```bash
.venv/bin/python -B -m unittest discover -s tests -q
```

Os testes usam credenciais fictícias, desativam o `.env` e bloqueiam a sessão HTTP real. Cobrem consultas, associações, cache, erros, filtros, CSV e páginas. Erros simulados podem aparecer no log; confira o resultado final da suíte.

Testes offline não substituem a validação com a versão e as permissões do APIC de destino. Antes de atualizar uma instalação, confira interfaces conhecidas, um vPC, um BD com subnet e um L3Out do ambiente.

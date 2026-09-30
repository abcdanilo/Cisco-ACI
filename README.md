# Diretório ativo do desenvolvimento

## Localizar servidor

Em **Localizar servidor** (`/endpoint_lookup`), selecione IP/MAC exato ou
nome/descrição do endpoint. A pesquisa por nome é parcial e ignora maiúsculas,
usando os campos `contName`, `nameAlias`, `name` e `descr` retornados em `fvCEp`.
Não consulta DNS, CMDB ou inventário externo. Se o nome estiver ausente, use IP/MAC.

Cada resultado preserva tenant, EPG, VLAN e caminhos do endpoint. Portas físicas
identificadas apresentam estado administrativo/operacional e velocidades configurada
e negociada separadas. PC/vPC mostra apenas membros com associação confirmada,
mantendo indicações de associação parcial e links para investigação. FEX e outros
caminhos sem mapeamento físico confirmado continuam identificados, sem inferir portas.

O CSV mantém os dados do endpoint e caminhos, respeitando o modo de busca; os
novos detalhes operacionais das portas são exibidos na tela. A opção Atualizar
renova as coletas utilizadas. A localização representa a informação disponível
na APIC, não uma confirmação externa da identidade do servidor.

## Consulta dinâmica de L3Out

No menu de conectividade, abra **L3Out — Selecionar tenant e L3Out** (`/l3out_explorer`).
As opções vêm de `fvTenant` e `l3extOut`, sem nomes fixos. A lista de L3Outs acompanha
o tenant escolhido e inclui grupos sem prefixos. A tabela pesquisa os prefixos de
External EPG (`l3extSubnet`), com paginação de 50 registros e CSV de toda a seleção.
Não representa rotas estáticas ou aprendidas. Os filtros são preservados na URL.
Consultas indisponíveis são exibidas como erro, não como inventário vazio.

Arquivos desta funcionalidade: `aci_l3out.py`, `templates/l3out_explorer.html`,
`static/l3out-explorer.js`, além de `app.py` e `templates/home.html` atualizados.

A partir de 29/09/2026, todos os arquivos são mantidos em `D:\Codex\APP-ACI`. A antiga cópia `sandbox-app` está descontinuada.

Para testar, abra PowerShell:

```powershell
cd D:\Codex\APP-ACI
.\.venv\Scripts\python.exe -B run_sandbox.py
```

Informe a senha do sandbox e abra http://127.0.0.1:8000. Para produção, utilize `app.py` pelo serviço existente e configure seu `.env`; não execute `run_sandbox.py`.

---
# APP-ACI

Painel Flask para consultar relatórios Cisco ACI no APIC, com filtros locais e exportação CSV.

## Instalação e execução

Use Python 3.10 ou superior. Na pasta do projeto:

```sh
python -m venv .venv
# Ative o ambiente virtual conforme seu sistema operacional.
python -m pip install -r requirements.txt
python app.py
```

O painel usa a porta `8000` por padrão. Mantenha o `.env` já existente no servidor; não o substitua pelo exemplo. As variáveis de ambiente do processo têm precedência sobre o arquivo `.env`.

`APIC_USER` e `APIC_PASS` são obrigatórias. Configure também `APIC_URL`. `APIC_VERIFY` aceita `true`, `false` ou caminho para uma CA. Para manter compatibilidade com a configuração anterior, a ausência dessa variável ainda desativa a validação TLS; o exemplo usa `true`.

O servidor iniciado por `python app.py` é o servidor de desenvolvimento do Flask. Caso o servidor já utilize um serviço WSGI, mantenha-o apontando para `app:app`.

## Atualizar uma instalação existente

Copie `app.py`, `aci_diagnostics.py`, `aci_portchannels.py`, a pasta `templates/` e a pasta `static/` juntos. A pasta `static/` contém os controles compartilhados e precisa ser servida pela aplicação ou pelo proxy. Preserve o `.env` e a configuração do serviço no servidor. Reinicie o processo da aplicação e recarregue as páginas do navegador com Ctrl+F5. As novas funcionalidades não exigem dependências Python adicionais.

Nenhum login de usuários foi acrescentado. As credenciais do `.env` são usadas exclusivamente na conexão do servidor com o APIC.

## Comportamento dos relatórios

- **Interfaces UP:** interfaces administrativamente habilitadas cujo estado operacional é `up`.
- **Todas as interfaces:** inclui interfaces administrativamente desabilitadas e apresenta os estados administrativo e operacional separadamente. Estado ausente é `unknown`.
- **Portas de acesso e AEP:** a associação operacional remove apenas o sufixo `/phys`; status e velocidade negociada são preservados. AEP mantém o DN completo de cada policy group, incluindo grupos `accportgrp` e `accbundle`.
- **VPC Ports:** uma linha por caminho lógico, com os dois nodes, agregados e membros identificados. A associação depende das relações e dos membros físicos; nomes ou números de port-channel iguais não bastam.
- **Endpoints IP:** deduplicação inclui o DN/contexto do endpoint; MAC/IP iguais em tenants distintos permanecem separados. O DN aparece na tela e no CSV.
- **Filtros:** seleções de tenant, pod, node, policy group e estado são exibidas quando existem dados correspondentes. Combinam-se com a busca e os filtros já existentes. São aplicadas no navegador.
- **CSV:** continua exportando o relatório completo, independentemente dos filtros de tela. Port-channels e endpoints receberam colunas de contexto.
- **Atualizar dados:** renova apenas o relatório solicitado e suas consultas dependentes, sem limpar todos os caches. A página informa o horário da coleta e se os dados vieram do cache.
- **Falhas parciais:** falhas por policy group aparecem em aviso e permanecem visíveis em respostas do cache. O aviso mostra até cinco detalhes; o log contém todas as falhas. Falha geral produz erro HTTP 500, sem apresentar um conjunto vazio como sucesso.
- **L3Outs:** consultas compartilham a coleta de subnets durante o TTL, reduzindo chamadas repetidas ao APIC. Os nomes de tenant/L3Out existentes foram preservados.

As APIs de relatórios e de busca de endpoints retornam arrays JSON. A API de detalhamento retorna um objeto com a interface e suas estatísticas. Metadados adicionais estão nos cabeçalhos `X-Collected-At`, `X-Data-Cache` e `X-Collection-Warnings`. A opção `?refresh=1` ignora o cache da consulta solicitada.

## Localizador de endpoints

Abra **Localizar por IP ou MAC** na página inicial (`/endpoint_lookup`). A busca é exata e aceita IPv4, IPv6 e MAC nos formatos `AA:BB:CC:DD:EE:FF`, `AA-BB-CC-DD-EE-FF`, `aabb.ccdd.eeff` e `aabbccddeeff`.

A consulta usa `fvCEp` com os filhos `fvIp` e `fvRsCEpToPathEp`. Mostra todos os IPs aprendidos, MAC, tenant, Application Profile, EPG, encapsulamento e caminhos informados pelo APIC. O BD aparece quando o controlador fornece `bdDn`; ausência é indicada como indisponível. Endpoints com o mesmo IP/MAC em contextos diferentes continuam separados. MAC sem IP aprendido também pode ser localizado.

A primeira busca coleta o inventário, que é reutilizado durante o TTL. Nenhuma consulta é disparada apenas ao abrir a tela vazia. O botão Atualizar dados renova o inventário; o CSV desta tela exporta somente os resultados do endereço pesquisado. Como o CSV consulta o cache no momento do download, pode refletir uma coleta mais recente que a tela quando o TTL expirar.

O link do EPG abre seu relatório com a busca preenchida. Caminhos físicos inequívocos oferecem um link para os detalhes da porta. Caminhos vPC, port-channel e FEX são apresentados com sua identidade original, sem inventar uma associação com uma porta física.

## Detalhamento e tráfego de interface

Abra **Detalhamento e Tráfego** (`/interface_details`) ou clique em um DN/caminho físico nos relatórios. Informe pod, node e interface (por exemplo, `eth1/1`). São apresentados descrição, estados administrativo e operacional, motivo, velocidades configurada/operacional, MTU, duplex e última mudança do link quando disponíveis.

As estatísticas são obtidas dos objetos `HDeqptIngrTotal5min-0` e `HDeqptEgrTotal5min-0` sob o DN da interface. A tela informa o início e o fim da amostra fornecidos pelo APIC, em horário local do navegador. Mostra taxas médias em Mbit/s, bytes/s e pacotes/s, contadores do intervalo e contadores acumulados separadamente. Conversão de bytes/s para Mbit/s: `bytesRateAvg × 8 / 1.000.000`.

Não há coleta histórica própria nem gráfico de tempo real. A amostra de cinco minutos é a última disponibilizada pelo APIC; se terminou há mais de 15 minutos, a tela a identifica como antiga. Falta de estatísticas aparece como indisponibilidade, e não como tráfego zero. Falhas parciais preservam os dados da interface e exibem um aviso. Valores acumulados grandes são preservados sem perda de precisão no navegador.

API: `/api/endpoint_lookup?q=<IP-ou-MAC>` e `/api/interface_details?dn=<DN-fisico>`. Entradas inválidas retornam 400; interface não encontrada retorna 404; falha geral da consulta retorna 500. Essas consultas não alteram a configuração do fabric.

Referências usadas para as estatísticas e a organização dos resultados:

- [Exemplo de endpoints do repositório indicado](https://github.com/timwukp/Cisco-APIC-REST-API/blob/master/aci-show-endpoints.py).
- [Exemplo de estatísticas de interfaces](https://github.com/timwukp/Cisco-APIC-REST-API/blob/master/aci-show-interface-stats.py).
- [Exemplo Cisco com o objeto histórico de cinco minutos e seus campos](https://community.cisco.com/t5/networking-blogs/cisco-aci-cli-with-corresponding-api-commands-part-1/ba-p/3658840).

## Visão consolidada de port-channel / vPC

Abra **Port-channel / vPC Consolidado** ou **VPC Ports** na página inicial. Tanto `/portchannel_overview` quanto `/portchannels` exibem a mesma visão consolidada.

O caminho lógico é obtido de `fabricPathEp` com `lagT=node` (vPC) ou `lagT=link` (port-channel). O DN define pod, switches e nome do grupo de bundle. O deployment de `infraAccBndlGrp` fornece as portas físicas, que são comparadas aos membros `pcRsMbrIfs` de cada `pcAggrIf` no mesmo pod/node. Uma associação só é confirmada quando há um único agregado candidato, com membros não vazios contidos no deployment, e esse agregado não é reivindicado por outro caminho lógico. Nomes iguais, por si só, nunca unem agregados.

Cada grupo apresenta os switches esperados, o número local do port-channel (que pode variar entre peers), modo, estado administrativo/operacional do agregado e membros com estado, velocidade e descrição. O estado operacional do agregado vem de `ethpmAggrIf`; ausência é exibida como indisponível. As portas têm links para a página de estatísticas. Um endpoint localizado em PC/vPC pode abrir esta visão pelo caminho lógico exato.

**Associação completa/parcial** descreve a cobertura do mapeamento, não a saúde do protocolo vPC nem o peer-link. Sem portas no deployment de um node, um único agregado com nome exato no mesmo pod/node do caminho lógico pode ser apresentado no grupo como **Associação por nome + topologia** (`mapping=inferred`, `coverage=correlated` quando todos os lados foram resolvidos). Seus membros são os coletados de `pcRsMbrIfs`. Essa correlação não confirma o vínculo físico e não é usada pelo diagnóstico de endpoint como associação confirmada. Um agregado reivindicado por mais de um caminho ou com candidatos duplicados permanece separado. Deployment com portas conflitantes impede essa alternativa. Um peer não resolvido continua visível; agregados sem associação nem correlação ficam em **Não associado**. O CSV preserva o nível de evidência na coluna Associacao.

É possível filtrar por texto, tipo e pod, atualizar a coleta e exportar apenas os grupos selecionados. O CSV contém uma linha por membro e preserva grupos sem membros com uma linha vazia de porta. Exporta todos os resultados dos filtros, inclusive além da primeira página. A coleta utiliza quatro consultas de classe, mais uma resolução de deployment por nome de bundle distinto (sujeitas à paginação). O cache evita repetir essas consultas em cada alteração de filtro. A disponibilidade e o formato do deployment devem ser confirmados no APIC do ambiente; caminhos FEX não reconhecidos não são consolidados por aproximação.

Novos arquivos necessários: `aci_portchannels.py`, `templates/portchannel_overview.html` e `static/portchannels.js`, além das atualizações dos arquivos comuns incluídas no pacote.

API: `/api/portchannel_overview`, com filtros opcionais `q`, `pod`, `node`, `state` (`up`, `down`), `kind` (`vpc`, `pc`, `unassociated`) e `path` (DN lógico exato). Node e estado devem coincidir no mesmo lado; o resultado preserva todos os peers do grupo. Exportação: `/export_csv/portchannel_overview` com os mesmos filtros. `refresh=1` renova a coleta. Todas as consultas são de leitura.

Referência do modelo de caminhos: [Cisco Live BRKACI-2101, exemplos de fabricPathEp e caminhos protegidos](https://community.cisco.com/kxiwq67737/attachments/kxiwq67737/12206936-discussions-aci/14398/1/BRKACI-2101.pdf).

## Testes offline

```sh
python -m unittest discover -s tests -v
```

Os testes definem credenciais fictícias, desativam a leitura do `.env` e bloqueiam chamadas reais da sessão HTTP. Validam associações de interfaces, estados, grupos AEP/bundle, identidade de switches/endpoints, TLS, cache, falhas, CSV e renderização das páginas.

Antes de atualizar produção, valide com o APIC do ambiente uma porta conhecida `up`, outra `down`, um AEP de porta individual e um AEP de bundle/vPC. A resolução de deployment foi testada com respostas simuladas; não houve conexão ao APIC real durante a implementação.

`app_py_additions_aep.py`, templates com `copy`/`old` e `home2.html` são arquivos legados. Não são carregados pela aplicação e não devem ser reaplicados sobre `app.py`.


## Tema claro e escuro em todas as páginas

Todas as 31 páginas oferecem um botão de tema. A escolha é salva no navegador, aplicada antes da exibição da página e mantida ao navegar ou recarregar. Abas abertas no mesmo navegador acompanham a alteração. O botão também pode ser acionado pelo teclado.

O controle comum está em `static/theme.js` e a paleta compartilhada em `static/theme.css`. Os templates carregam esses arquivos; os relatórios antigos também receberam cores adequadas ao tema claro.

Para aplicar apenas esta correção sobre a versão que já contém os diagnósticos e a visão consolidada de PC/vPC, copie as pastas `templates/` e `static/` do pacote. Reinicie o serviço para recarregar os templates e atualize o navegador com Ctrl+F5. Preserve o `.env` do servidor.


## Ficha de Leaf Access Port e utilização (laboratório)

Em Portas de acesso, clique no nome do Policy Group para abrir `/access_group?dn=...`. A ficha consulta os objetos de política associados e exibe valores, estado da relação e indicação de alvo padrão. AEP inclui suas relações filhas, como domínios, quando fornecidas pelo APIC.

O caminho de utilização cruza `infraRsAccBaseGrp.tDn` com o DN exato do grupo e `infraRsAccPortP.tDn` com o DN exato do perfil de interfaces. Mostra seletores, intervalos de cartões/portas e intervalos de IDs dos switches. Não infere interfaces operacionais nem pod a partir desses intervalos. Relações ausentes ou consultas incompletas permanecem explícitas. Seletores FEX e formatos alternativos ao `infraHPortS/infraPortBlk` não são resolvidos por esta ficha.

Arquivos necessários: `aci_access.py`, `templates/access_group.html`, `static/access-group.js` e as atualizações de `app.py` e `templates/report_acc_ports.html`. O launcher `run_sandbox.py` identifica o laboratório. As credenciais não estão nos arquivos.


## Painel operacional e falhas relacionadas

A página inicial exibe oito indicadores obtidos dos mesmos relatórios: switches leaf/spine, interfaces físicas (total, up e down), endpoints, falhas critical, major e total incluindo cleared. Cada indicador mostra o horário da respectiva coleta, abre seu relatório com filtros exatos e permite atualização manual. Falhas de consulta aparecem como indisponível, sem converter em zero. As coletas não são um snapshot atômico.

As fichas de interface e Leaf Access Port consultam `/api/object_faults?dn=...`. A seleção considera o DN do objeto, o campo affected e descendentes com separador `/`, sem associação por nome ou substring livre. Políticas compartilhadas não são incluídas automaticamente. São exibidos severidade, código, descrição, causa, criação, última transição e DN. Falhas de consulta são diferenciadas de ausência de registros. O inventário de faultInst usa o cache compartilhado existente; ainda não há assinatura em tempo real ou histórico local.


## Histórico de eventos e alterações

Abra `/history` pelo painel inicial ou pelo link nas fichas de interface/Policy Group. O histórico consulta `eventRecord` para eventos e `aaaModLR` para alterações de configuração. Mostra horário, usuário, descrição, ação, severidade, código, causa e objeto afetado. O filtro opcional de DN é exato e usa o atributo `affected`, não o DN do registro de log.

O período inicial é de 24 horas, com limite de 31 dias por consulta. A interface recebe datas no fuso do navegador e as envia com UTC. A API aplica os filtros no APIC e busca apenas 50 registros por página, em ordem decrescente de criação. Durante a paginação mantém o mesmo intervalo. Um botão Próxima pode levar a uma página vazia se a anterior contiver exatamente 50 registros e não houver mais dados. Logs podem mudar durante a navegação.

São registros retidos no APIC, não armazenamento local permanente nem diff antes/depois. O conteúdo bruto de changeSet não é exibido. Falha de consulta é apresentada separadamente de resultado vazio. Validação: 45 testes offline passaram; eventos e auditoria retornaram registros reais, com paginação, filtro vazio e layout móvel verificados.

Novos arquivos: `aci_history.py`, `templates/history.html`, `static/history.js`, além das atualizações de app.py, navegação e atalhos.

Referência: https://www.cisco.com/c/en/us/td/docs/switches/datacenter/aci/apic/sw/all/faults/guide/b_APIC_Faults_Errors/b_IFC_Faults_Errors_chapter_010.html


A visão PC/vPC consolidada usa tabela compacta, uma linha por grupo lógico, portas e velocidades identificadas por node e detalhes expansíveis. Paginação de dez grupos preserva peers juntos; CSV contém todos os grupos filtrados, não apenas a página visível, com uma linha por membro para análise. Avisos de associação parcial permanecem separados do estado operacional. Reinicie o aplicativo e recarregue com Ctrl+F5 após atualizar os arquivos.


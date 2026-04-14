"""
Configuração do Webhook Dispatcher.

Para adicionar um novo bot:
  1. Adicione uma entrada em BOTS com nome, URL e critérios de roteamento.
  2. Reinicie o serviço: systemctl restart webhook-dispatcher

Critérios de roteamento (qualquer um que casar → o bot recebe):
  match_tags    : o contato tem uma tag cujo nome contenha alguma dessas strings
  match_dept    : o departamento do contato contém alguma dessas strings
  match_channel : o canal/source do evento contém alguma dessas strings
  default       : True → recebe eventos que não casaram com nenhum bot específico
"""

# ── Timeout de encaminhamento (segundos) ─────────────────────────────────────
FORWARD_TIMEOUT = 10

# ── Nível de log ──────────────────────────────────────────────────────────────
DISPATCHER_LOG_LEVEL = "INFO"

# ── Registro de bots ──────────────────────────────────────────────────────────
BOTS = [
    {
        "name": "BOT-PJ",
        "url":  "http://127.0.0.1:8001/webhook/tallos",

        # Roteia para o PJ quando o contato tiver qualquer uma dessas tags
        "match_tags": ["pj", "corporativo", "empresa", "treinamento pj"],

        # Ou quando o departamento contiver qualquer uma dessas strings
        "match_dept": ["pj", "corporativo", "treinamentos pj"],

        # Ou quando o canal/source indicar PJ
        "match_channel": [],

        # NÃO é default — só recebe eventos que casarem acima
        "default": False,
    },
    {
        "name": "BOT-MBA",
        "url":  "http://127.0.0.1:8002/webhook/tallos",

        # Roteia para MBA quando tiver essas tags ou departamento
        "match_tags": ["mba", "pós", "pos-graduacao", "impacta mba"],
        "match_dept": ["mba", "pós-graduação", "pos graduacao"],
        "match_channel": [],

        # É o default — recebe tudo que não casou com nenhum bot específico
        "default": True,
    },

    # ── Exemplo de novo bot (descomente e edite para ativar) ──────────────────
    # {
    #     "name": "BOT-VENDAS",
    #     "url":  "http://127.0.0.1:8003/webhook/tallos",
    #     "match_tags":    ["vendas", "comercial"],
    #     "match_dept":    ["vendas"],
    #     "match_channel": [],
    #     "default": False,
    # },
]

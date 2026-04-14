# Deploy do Webhook Dispatcher

## 1. Copiar arquivos para o servidor

```bash
cp -r webhook-dispatcher /opt/webhook-dispatcher
cd /opt/webhook-dispatcher
```

## 2. Criar ambiente virtual e instalar dependências

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

## 3. Instalar e iniciar o serviço systemd

```bash
cp webhook-dispatcher.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable webhook-dispatcher
systemctl start webhook-dispatcher
systemctl status webhook-dispatcher
```

## 4. Atualizar o nginx

Edite o arquivo de configuração do nginx:
```bash
nano /etc/nginx/sites-enabled/default
```

Substitua os blocos de `/webhook/tallos`, `/webhook/tallospj` e `/webhook/tallosmba`
pelo conteúdo de `nginx-snippet.conf`.

Depois:
```bash
nginx -t && systemctl reload nginx
```

## 5. Verificar se está funcionando

```bash
# Health check
curl http://localhost:8000/health

# Teste de roteamento (simula contato PJ)
curl -s -X POST http://localhost:8000/webhook/tallos \
  -H "Content-Type: application/json" \
  -d '{"contact":{"tags":[{"name":"PJ"}],"department":{"name":"Treinamentos PJ"}}}'

# Ver logs em tempo real
journalctl -u webhook-dispatcher -f
```

## 6. Verificar porta do BOT MBA

O dispatcher aponta para `http://127.0.0.1:8002/webhook/tallos` para o MBA.
Confirme a porta correta do BOT MBA:
```bash
systemctl status botmba | grep "port\|8002\|8001"
ss -tlnp | grep gunicorn
```

Se a porta for diferente, edite `config.py` e reinicie:
```bash
nano /opt/webhook-dispatcher/config.py
systemctl restart webhook-dispatcher
```

## 7. Para adicionar um novo bot no futuro

Edite `/opt/webhook-dispatcher/config.py` e adicione uma entrada em `BOTS`:

```python
{
    "name": "BOT-VENDAS",
    "url":  "http://127.0.0.1:8003/webhook/tallos",
    "match_tags": ["vendas"],
    "match_dept": ["comercial"],
    "match_channel": [],
    "default": False,
},
```

Depois: `systemctl restart webhook-dispatcher`

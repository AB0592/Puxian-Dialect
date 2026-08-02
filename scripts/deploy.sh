#!/bin/bash
# ============================================================
# 莆仙话训练 — 公网部署助手
# ============================================================
# 在你的 MacBook Pro 上运行：
#   chmod +x deploy.sh && ./deploy.sh
# ============================================================

echo "=============================="
echo "  莆仙话训练 · 公网部署"
echo "=============================="
echo ""

# ---- Step 1: 注册域名 ----
echo "【Step 1】注册域名 puxianhua.app"
echo ""
echo "请前往 Cloudflare 注册域名："
echo "  1. 打开 https://dash.cloudflare.com → 注册/登录"
echo "  2. 点击 'Add a Site' → 输入 puxianhua.app"
echo "  3. 选择 'Free' 计划 → 完成购买 (~$12/年)"
echo "  4. 在 DNS 设置中添加一条 A 记录指向你的服务器 IP"
echo ""
echo "完成后按 Enter 继续..."
read

# ---- Step 2: 安装 cloudflared ----
echo ""
echo "【Step 2】安装 Cloudflare Tunnel"
echo ""

if ! which cloudflared &>/dev/null; then
    echo "正在下载 cloudflared..."
    brew install cloudflared
fi

echo ""
echo "【Step 3】创建隧道"
echo "请登录 Cloudflare → Zero Trust → Tunnels → Create a tunnel"
echo "选择 cloudflared 类型，复制 Token"
echo ""
echo "安装完成后，隧道会指向："
echo "  http://localhost:8520   (/api/* 后端 API)"
echo "  https://localhost:8521  (/flutter/* Flutter 前端)"
echo ""
echo "Cloudflare 会自动处理 HTTPS 证书！"
echo ""

# ---- Step 4: 隧道配置文件 ----
mkdir -p ~/.cloudflared

cat > ~/.cloudflared/config_puxian.yml << 'TUNNEL'
# 隧道配置 — 安装后运行：
# cloudflared tunnel --config ~/.cloudflared/config_puxian.yml run
tunnel: puxianhua-app
credentials-file: ~/.cloudflared/puxianhua-app.json

ingress:
  # Flutter Web 前端
  - hostname: puxianhua.app
    service: https://100.101.76.95:8521
    originRequest:
      noTLSVerify: true  # 后端是自签名证书

  # 后端 API（可选独立子域名）
  - hostname: api.puxianhua.app
    service: http://100.101.76.95:8520

  # 兜底
  - service: http_status:404
TUNNEL

echo "配置文件已生成: ~/.cloudflared/config_puxian.yml"
echo ""
echo "=============================="
echo "  部署完成！"
echo ""
echo "  域名: https://puxianhua.app"
echo "  用户注册 → 声纹录入 → 开始训练"
echo "=============================="

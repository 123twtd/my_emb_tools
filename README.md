# 串口助手 (Python)

基于 PyQt5 的多功能串口与视觉工具，支持串口通信、示波器、图传、ArUco 视觉定位、镜头去畸变标定、UDP/TCP/API 网络服务等。

## 功能

- **基础串口**：UART 收发、协议解析
- **UDP 通道**：UDP 收发（可替代串口通道）
- **示波器**：实时波形显示
- **图传**：摄像头采集与图像发送
- **ArUco 定位**：标记检测、场地标定、车辆位姿、UDP 广播
- **镜头去畸变**：棋盘格标定向导、命名配置、摄像头绑定、自动加载
- **网络服务**：HTTP API、WebSocket、TCP、摄像头 MJPEG 广播（可选）

## 环境要求

- Python 3.9+
- Windows / Linux（摄像头与串口驱动因平台而异）

## 安装

```bash
git clone https://github.com/123twtd/my_emb_tools.git
cd my_emb_tools
pip install -r requirements.txt
```

或使用 Conda：

```bash
conda env create -f environment.yml
conda activate serial-assistant
```

## 运行

```bash
python main.py
```

## 配置

| 文件 | 说明 |
|------|------|
| `config/app.json` | 网络服务、UDP 默认、主题等 |
| `config/tabs.json` | Tab 启用与加载顺序 |
| `config/aruco_config.yaml` | ArUco 字典、场地坐标、去畸变配置集 |

镜头标定 NPZ 保存在 `config/calib/`（已加入 `.gitignore`，勿提交个人标定数据）。

## 开源协议

[MIT License](LICENSE)

## 贡献

欢迎 Issue 与 Pull Request。

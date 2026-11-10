FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 设置时区为中国时区
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

ENV PATH="/usr/local/bin:${PATH}"

# 复制项目文件
COPY main.py push.py config.py log_utils.py scheduler.py ./

# 安装 Python 依赖
# curl_cffi：模拟 Chrome TLS/HTTP2 指纹（反检测 P0-1），main.py 会在未安装时自动回退
RUN python -m pip install --no-cache-dir \
    'requests>=2.32.3' \
    'urllib3>=2.2.3' \
    'curl_cffi>=0.7.0'

# 定时调度统一由 scheduler.py（APScheduler，CRON_SCHEDULE 环境变量）负责，
# 无需系统 cron（原 cron.d 双轨代码从未生效，已移除）

# 启动命令
CMD ["python", "scheduler.py"]

# 启动 Client_test.py 并屏蔽 paramiko/cryptography 的弃用警告
python -W ignore::DeprecationWarning "$PSScriptRoot\Client_test.py" $args

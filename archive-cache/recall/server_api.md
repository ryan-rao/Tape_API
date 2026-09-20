# 服务器信息与性能监控 REST API 文档

## 1. 基本说明
- 基础路径：`/api/v1`
- 数据格式：`application/json`
- 数据分类：静态配置 + 动态性能

## 2. 获取服务器列表
GET /api/v1/servers

```json
{
  "code": 0,
  "message": "success",
  "data": [
    {
      "id": "srv-001",
      "hostname": "node-01",
      "ip": "192.168.1.10",
      "os": "Linux",
      "status": "running"
    }
  ]
}
```

## 3. 获取服务器完整硬件配置
GET /api/v1/servers/{serverId}/spec

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "serverId": "srv-001",
    "hostname": "node-01",
    "os": "Ubuntu 22.04",
    "kernel": "5.15.0",
    "cpu": {"model":"Intel Xeon","cores":20,"threads":40},
    "memory": {"totalGB":128,"type":"DDR4"},
    "disk": {
      "hdd":[{"name":"sda","sizeGB":2000}],
      "nvme":[{"name":"nvme0n1","sizeGB":1000}]
    },
    "networkCards":[{"name":"eth0","ip":"192.168.1.10","speedMbps":1000}]
  }
}
```

## 4. 获取服务器实时性能数据
GET /api/v1/servers/{serverId}/metrics

```json
{
  "code":0,
  "data":{
    "timestamp":"2026-02-06 14:30:00",
    "cpu":{"usagePercent":45.6},
    "memory":{"usedGB":72,"usagePercent":56.2},
    "disk":{"nvme":[{"readMBps":850,"writeMBps":600}]},
    "network":[{"name":"eth0","rxMbps":120,"txMbps":95}]
  }
}
```

## 5. 健康检查
GET /api/v1/health

```json
{"status":"UP"}
```

## 6. 错误返回
```json
{"code":1001,"message":"server not found"}
```

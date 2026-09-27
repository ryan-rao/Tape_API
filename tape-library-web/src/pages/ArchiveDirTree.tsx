import { useCallback, useEffect, useState } from 'react';
import {
  Alert, Button, Card, Col, Descriptions, Empty, Row, Space, Spin, Tag, Tree, Typography,
} from 'antd';
import { FileOutlined, FolderOutlined, ReloadOutlined } from '@ant-design/icons';
import { rawRequest } from '../api/client';

const { Text } = Typography;

function fmtBytes(n?: number | null): string {
  if (n == null) return '-';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i += 1; }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${u[i]}`;
}

const STATE_COLORS: Record<string, string> = {
  cached: 'orange', buffering: 'orange', archiving: 'processing',
  archived: 'green', failed: 'red', sealed: 'cyan', flushing: 'processing',
};

function kindTag(f: any) {
  if (f?.ltfs_path) return <Tag color="purple">LTFS</Tag>;
  if (f?.kind === 'container_member') return <Tag color="blue">小文件·聚合</Tag>;
  return <Tag color="geekblue">大文件·直写</Tag>;
}

function toTreeNodes(node: any): any {
  const isDir = node.type === 'dir';
  return {
    key: `d:${node.path}` || 'd:/',
    title: isDir ? (
      <Space size={4}>
        <FolderOutlined style={{ color: '#faad14' }} />
        <Text strong>{node.name}</Text>
        <Text type="secondary" style={{ fontSize: 12 }}>{node.file_count}文件 · {fmtBytes(node.size_bytes)}</Text>
      </Space>
    ) : (
      <Space size={4} wrap>
        <FileOutlined />
        <Text>{node.name}</Text>
        {kindTag(node.file)}
        <Text type="secondary" style={{ fontSize: 12 }}>{fmtBytes(node.file?.size_bytes)}</Text>
        {node.file?.state === 'archived' && node.file?.media_barcode && (
          <Tag color="volcano" style={{ marginInlineEnd: 0 }}>{node.file.media_barcode}</Tag>
        )}
        {node.file?.state !== 'archived' && (
          <Tag color={STATE_COLORS[node.file?.state] || 'default'} style={{ marginInlineEnd: 0 }}>{node.file?.state}</Tag>
        )}
      </Space>
    ),
    ...(isDir ? { children: node.children?.map(toTreeNodes) } : {}),
    raw: node,
  };
}

function FileDetail({ f }: { f: any }) {
  const isMember = f.kind === 'container_member';
  const ltfs = !!f.ltfs_path;
  return (
    <Card size="small" title={<Space wrap>{kindTag(f)}<Text code copyable={{ text: f.file_id }} style={{ fontSize: 12 }}>{f.file_id}</Text></Space>}>
      <Descriptions size="small" column={1} bordered>
        <Descriptions.Item label="文件名">{f.filename}</Descriptions.Item>
        <Descriptions.Item label="大小 / SHA256">{fmtBytes(f.size_bytes)} · <Text code style={{ fontSize: 11 }} copyable={{ text: f.sha256 }}>{String(f.sha256 || '').slice(0, 20)}…</Text></Descriptions.Item>
        {ltfs ? (
          <Descriptions.Item label="落带位置（LTFS）">
            磁带 <Text strong>{f.media_barcode ?? '未落带'}</Text>
            {f.tape_block_index != null && <> · 块 #{f.tape_block_index}</>}
            <br />LTFS 路径 <Text code>{f.ltfs_path}</Text>
          </Descriptions.Item>
        ) : isMember ? (
          <Descriptions.Item label="落带位置（小文件聚合）">
            聚合容器 <Text code>{String(f.container_id || '').slice(0, 8)}</Text>
            （{f.container_file_count ?? '-'} 件 · {fmtBytes(f.container_size_bytes)} · 状态 {f.container_state ?? '-'}）
            <br />容器内偏移 <Text strong>{f.offset_in_container != null ? `${f.offset_in_container} B` : '-'}</Text>
            {f.media_barcode
              ? <> → 写在磁带 <Text strong>{f.media_barcode}</Text>{f.tape_block_index != null && <> 磁带块 <Text strong>#{f.tape_block_index}</Text></>}{f.tape_block_index == null && <>（LTFS 容器，位置=容器内偏移）</>}</>
              : '（容器未落带）'}
          </Descriptions.Item>
        ) : (
          <Descriptions.Item label="落带位置（大文件直写）">
            {f.media_barcode
              ? <>独立写在磁带 <Text strong>{f.media_barcode}</Text> 磁带块 <Text strong>#{f.tape_block_index}</Text></>
              : '（未落带）'}
          </Descriptions.Item>
        )}
        <Descriptions.Item label="状态">
          <Tag color={STATE_COLORS[f.state] || 'default'}>{f.state}</Tag>
          {' '}存储 {String(f.storage)}
          {f.recalls > 0 && <> · 已召回 {f.recalls} 次</>}
        </Descriptions.Item>
        <Descriptions.Item label="时间">
          上传 {String(f.created_at ?? '-').slice(0, 19)} · 落带 {f.archived_at ? String(f.archived_at).slice(0, 19) : '-'}
        </Descriptions.Item>
      </Descriptions>
    </Card>
  );
}

export default function ArchiveDirTree() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [sel, setSel] = useState<any>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const r = await rawRequest('GET', '/archive/dirtree');
    if (r.success) setData(r.data);
    setLoading(false);
  }, []);
  useEffect(() => { load(); }, [load]);

  const s = data?.summary;
  return (
    <Card size="small" title="归档目录树 GET /archive/dirtree"
      extra={<Space wrap>
        {s && (
          <Text type="secondary" style={{ fontSize: 12 }}>
            {s.files_total} 文件 · 小文件聚合 {s.small_aggregated}（{s.containers_total} 容器） · 大文件直写 {s.large_direct} · 磁带 {s.tapes?.length ?? 0} 卷
          </Text>
        )}
        <Button size="small" icon={<ReloadOutlined />} loading={loading} onClick={load}>刷新</Button>
      </Space>}>
      <Alert type="info" showIcon style={{ marginBottom: 8 }}
        message="从元数据构建的客户目录树：小文件显示 聚合容器+容器内偏移+所在磁带/磁带块；大文件显示 直写磁带条码+磁带块；缓存已淘汰的文件仍在树上。" />
      {!data ? (
        <div style={{ padding: 24, textAlign: 'center' }}><Spin /></div>
      ) : !data.root?.children?.length ? (
        <Empty description="暂无归档文件" />
      ) : (
        <Row gutter={12}>
          <Col xs={24} lg={10}>
            <div style={{ maxHeight: 560, overflow: 'auto', border: '1px solid #f0f0f0', borderRadius: 4, padding: 8, background: '#fafafa' }}>
              <Tree showLine defaultExpandAll
                treeData={[toTreeNodes(data.root)]}
                onSelect={(_k, info: any) => setSel(info.node.raw)} />
            </div>
          </Col>
          <Col xs={24} lg={14}>
            {sel?.type === 'file' ? (
              <FileDetail f={sel.file} />
            ) : sel?.type === 'dir' ? (
              <Card size="small" title={`目录 ${sel.path || '/'}`}>
                <Descriptions size="small" column={1} bordered>
                  <Descriptions.Item label="文件数（含子目录）">{sel.file_count}</Descriptions.Item>
                  <Descriptions.Item label="总大小">{fmtBytes(sel.size_bytes)}</Descriptions.Item>
                </Descriptions>
              </Card>
            ) : (
              <Empty description="点击左侧文件查看磁带落位详情" />
            )}
          </Col>
        </Row>
      )}
    </Card>
  );
}

import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import App from './App';
import Dashboard from './pages/Dashboard';
import Libraries from './pages/Libraries';
import LibraryDetail from './pages/LibraryDetail';
import Drives from './pages/Drives';
import DriveDetail from './pages/DriveDetail';
import Tapes from './pages/Tapes';
import TestCenter from './pages/TestCenter';
import Operations from './pages/Operations';
import Audit from './pages/Audit'
import ApiLogs from './pages/ApiLogs';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider locale={zhCN}>
      <BrowserRouter>
        <Routes>
          <Route element={<App />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/libraries" element={<Libraries />} />
            <Route path="/libraries/:changer" element={<LibraryDetail />} />
            <Route path="/drives" element={<Drives />} />
            <Route path="/drives/:nst" element={<DriveDetail />} />
            <Route path="/tapes" element={<Tapes />} />
            <Route path="/tests" element={<TestCenter />} />
            <Route path="/operations" element={<Operations />} />
            <Route path="/audit" element={<Audit />} />
            <Route path="/api-logs" element={<ApiLogs />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  </React.StrictMode>,
);

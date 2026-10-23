import { lazy, Suspense } from 'react';
import { createBrowserRouter, Navigate, Outlet } from 'react-router-dom';
import { Spin } from 'antd';
import { AppLayout } from '../components/layout/AppLayout';

const DocumentManagementPage = lazy(() => import('../pages/documents/DocumentManagementPage').then((module) => ({ default: module.DocumentManagementPage })));
const WikiPageManagementPage = lazy(() => import('../pages/wiki/WikiPageManagementPage').then((module) => ({ default: module.WikiPageManagementPage })));
const WorkbenchPage = lazy(() => import('../pages/workbench/WorkbenchPage').then((module) => ({ default: module.WorkbenchPage })));
const FeedbackOpsPage = lazy(() => import('../pages/feedback/FeedbackOpsPage').then((module) => ({ default: module.FeedbackOpsPage })));

function LazyPage({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={<Spin />}>
      {children}
    </Suspense>
  );
}

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout><Outlet /></AppLayout>,
    children: [
      { index: true, element: <Navigate to="/documents" replace /> },
      { path: 'documents', element: <LazyPage><DocumentManagementPage /></LazyPage> },
      { path: 'wiki', element: <LazyPage><WikiPageManagementPage /></LazyPage> },
      { path: 'workbench', element: <LazyPage><WorkbenchPage /></LazyPage> },
      { path: 'feedback', element: <LazyPage><FeedbackOpsPage /></LazyPage> },
    ],
  },
]);

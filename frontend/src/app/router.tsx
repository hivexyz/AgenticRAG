import { createBrowserRouter, Navigate, Outlet } from 'react-router-dom';
import { AppLayout } from '../components/layout/AppLayout';
import { DocumentManagementPage } from '../pages/documents/DocumentManagementPage';
import { WorkbenchPage } from '../pages/workbench/WorkbenchPage';

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout><Outlet /></AppLayout>,
    children: [
      { index: true, element: <Navigate to="/documents" replace /> },
      { path: 'documents', element: <DocumentManagementPage /> },
      { path: 'workbench', element: <WorkbenchPage /> },
    ],
  },
]);

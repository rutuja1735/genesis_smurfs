import { WorkspaceProvider } from '../../components/workspace-provider';
import { WorkspaceShell } from '../../components/workspace-shell';

export default function WorkspaceLayout({ children }) {
  return <WorkspaceProvider><WorkspaceShell>{children}</WorkspaceShell></WorkspaceProvider>;
}

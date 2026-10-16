import './globals.css';
import { WorkspaceProvider } from '../components/workspace-provider';
import { WorkspaceShell } from '../components/workspace-shell';

// The dashboard's date and chart window must be current on every request.
export const dynamic = 'force-dynamic';

export const metadata = {
  title: { default: 'Agentgaurd · Workspace', template: '%s · Agentgaurd' },
  description: 'Run, observe, and evaluate your agents in one workspace.',
};

export default function RootLayout({ children }) {
  return <html lang="en"><body><WorkspaceProvider><WorkspaceShell>{children}</WorkspaceShell></WorkspaceProvider></body></html>;
}

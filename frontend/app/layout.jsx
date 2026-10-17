import './globals.css';
import './marketing.css';

// The dashboard's date and chart window must be current on every request.
export const dynamic = 'force-dynamic';

export const metadata = {
  title: { default: 'Agentguard · Workspace', template: '%s · Agentguard' },
  description: 'Run, observe, and evaluate your agents in one workspace.',
};

export default function RootLayout({ children }) {
  // Browser extensions can add attributes to <html> before React hydrates.
  // Suppress only this root mismatch; child hydration warnings remain visible.
  return <html lang="en" suppressHydrationWarning><body>{children}</body></html>;
}

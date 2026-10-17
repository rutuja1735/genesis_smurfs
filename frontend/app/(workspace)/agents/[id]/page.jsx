import { notFound } from 'next/navigation';
import { AgentDetail } from '../../../../components/agents';
export const metadata = { title: 'Agent workspace' };
export default async function Page({ params }) { const { id } = await params; if (!['email', 'slack', 'banking'].includes(id)) notFound(); return <AgentDetail id={id} />; }

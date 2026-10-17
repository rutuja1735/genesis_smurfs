import { RunDetail } from '../../../../components/run-detail';
export const metadata = { title: 'Run details' };
export default async function Page({ params }) { const { id } = await params; return <RunDetail id={id} />; }

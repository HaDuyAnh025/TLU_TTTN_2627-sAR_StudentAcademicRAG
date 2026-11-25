import { Suspense } from "react";
import { ConversationView } from "@/components/student/ConversationView";

async function ConversationContent({
  params,
}: {
  params: PageProps<"/c/[conversationId]">["params"];
}) {
  const { conversationId } = await params;
  return <ConversationView key={conversationId} conversationId={conversationId} />;
}

export default function ConversationPage(props: PageProps<"/c/[conversationId]">) {
  return (
    <Suspense
      fallback={
        <div role="status" className="px-6 py-14 text-body text-text-muted">
          Đang tải cuộc trò chuyện…
        </div>
      }
    >
      <ConversationContent params={props.params} />
    </Suspense>
  );
}

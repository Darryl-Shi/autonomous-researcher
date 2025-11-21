import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";

interface StreamingMarkdownProps {
    content: string;
    /**
     * Optional stable key to decide when to trigger the entry animation.
     * Use the thought/step id so streaming updates don't re-trigger the fade.
     */
    animateKey?: string | number;
    wrapperClassName?: string;
    markdownClassName?: string;
}

/**
 * Markdown block that lightly fades in whenever its content changes.
 * This keeps streamed tokens feeling alive without re-mounting the whole row.
 */
export function StreamingMarkdown({ content, animateKey, wrapperClassName, markdownClassName }: StreamingMarkdownProps) {
    const [isUpdating, setIsUpdating] = useState(false);
    const key = animateKey ?? content;
    const animatedRef = useRef(false);
    const prevKeyRef = useRef<string | number | null>(null);
    const prevContentRef = useRef<string>("");

    useEffect(() => {
        const keyChanged = prevKeyRef.current !== key;
        if (keyChanged) {
            animatedRef.current = false; // allow animation for new item
            prevKeyRef.current = key;
        }

        const hadContent = prevContentRef.current.length > 0;
        const hasContent = content.length > 0;
        prevContentRef.current = content;

        // Trigger once when a new item receives its first content.
        if (!animatedRef.current && hasContent && !hadContent) {
            animatedRef.current = true;
            setIsUpdating(true);
            const timeout = window.setTimeout(() => setIsUpdating(false), 420);
            return () => window.clearTimeout(timeout);
        }
    }, [key, content]);

    return (
        <div className={cn("stream-fade", isUpdating && "stream-fade--active", wrapperClassName, markdownClassName)}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {content}
            </ReactMarkdown>
        </div>
    );
}

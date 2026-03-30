async def normalize_sse_stream(aiter_lines):
    data_lines: list[str] = []

    def flush_event():
        if not data_lines:
            return None
        payload = "\n".join(data_lines)
        data_lines.clear()
        return f"data: {payload}"

    async for raw_line in aiter_lines:
        line = raw_line.rstrip("\r")
        if line == "":
            event = flush_event()
            if event:
                yield event
            continue

        if line.startswith("data:"):
            content = line[5:]
            if content.startswith(" "):
                content = content[1:]
            data_lines.append(content)
            continue

        if data_lines:
            continue

        elif line.startswith("{"):
            yield f"data: {line}"
        elif line.startswith(":"):
            continue

    event = flush_event()
    if event:
        yield event

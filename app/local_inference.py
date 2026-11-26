"""CPU-friendly local defaults and streaming thought-tag suppression."""
MAX_SECONDS = 120
TIMEOUT_MESSAGE = (
    "Local processing stopped after 2 minutes to limit CPU use. "
    "No incomplete answer was saved. Ask about a smaller section or choose Cloud."
)


def options(prompt_bytes, max_tokens):
    output = min(1024, max(1, max_tokens))
    estimated = prompt_bytes // 3 + output + 1024
    context = next((n for n in (8192, 16384, 32768) if n >= estimated), 32768)
    return {"num_ctx": context, "num_predict": output, "num_thread": 4}


class ThoughtFilter:
    def __init__(self):
        self.buffer = ""
        self.inside = False

    def feed(self, text):
        self.buffer += text
        output = ""
        while self.buffer:
            marker = "</think>" if self.inside else "<think>"
            index = self.buffer.find(marker)
            if index >= 0:
                if not self.inside:
                    output += self.buffer[:index]
                self.buffer = self.buffer[index + len(marker):]
                self.inside = not self.inside
                continue
            keep = max((n for n in range(1, len(marker))
                        if self.buffer.endswith(marker[:n])), default=0)
            if not self.inside:
                output += self.buffer[:-keep] if keep else self.buffer
            self.buffer = self.buffer[-keep:] if keep else ""
            break
        return output

    def finish(self, tool_calls=False):
        if self.inside:
            if tool_calls:
                # A structured tool call can complete without visible thought delimiters.
                self.inside=False;self.buffer=""
                return ""
            raise ValueError("The local model did not finish its thinking section. No incomplete answer was saved.")
        value, self.buffer = self.buffer, ""
        return value

package dev.saseq.services;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Service
public class DiscordRestReadService {

    private static final String DISCORD_API = "https://discord.com/api/v10";

    private final String token;
    private final HttpClient httpClient;
    private final ObjectMapper objectMapper;

    @Value("${DISCORD_GUILD_ID:}")
    private String defaultGuildId;

    public DiscordRestReadService(@Value("${DISCORD_TOKEN:}") String token) {
        if (token == null || token.isEmpty()) {
            throw new IllegalArgumentException("DISCORD_TOKEN cannot be empty");
        }
        this.token = token;
        this.httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(15))
                .build();
        this.objectMapper = new ObjectMapper();
    }

    @Tool(name = "read_messages_rest", description = "Read message history from a channel through Discord REST without requiring gateway readiness")
    public String readMessagesRest(@ToolParam(description = "Discord channel ID") String channelId,
                                   @ToolParam(description = "Number of messages to retrieve (1-100)", required = false) String count,
                                   @ToolParam(description = "Message ID to fetch messages before this message", required = false) String before,
                                   @ToolParam(description = "Message ID to fetch messages after this message", required = false) String after,
                                   @ToolParam(description = "Message ID to fetch messages around this message", required = false) String around) {
        if (channelId == null || channelId.isBlank()) {
            throw new IllegalArgumentException("channelId cannot be null");
        }
        int limit = parseMessageLimit(count);
        validateCursorParameters(before, after, around);

        List<String> query = new ArrayList<>();
        query.add("limit=" + limit);
        if (isProvided(before)) query.add("before=" + urlEncode(before));
        if (isProvided(after)) query.add("after=" + urlEncode(after));
        if (isProvided(around)) query.add("around=" + urlEncode(around));

        JsonNode messages = getJson("/channels/" + channelId + "/messages?" + String.join("&", query));
        if (!messages.isArray()) {
            throw new IllegalStateException("Discord REST returned non-array messages response");
        }

        List<String> formatted = new ArrayList<>();
        for (JsonNode message : messages) {
            formatted.add(formatMessage(message));
        }
        return "**Retrieved " + formatted.size() + " messages:** \n" + String.join("\n", formatted);
    }

    @Tool(name = "list_active_threads_rest", description = "List active threads through Discord REST without requiring gateway readiness")
    public String listActiveThreadsRest(@ToolParam(description = "Discord server ID", required = false) String guildId) {
        guildId = resolveGuildId(guildId);
        Map<String, String> channelNames = channelNamesById(guildId);
        JsonNode payload = getJson("/guilds/" + guildId + "/threads/active");
        JsonNode threads = payload.path("threads");
        if (!threads.isArray() || threads.isEmpty()) {
            return "No active threads found in the server.";
        }

        List<String> formatted = new ArrayList<>();
        for (JsonNode thread : threads) {
            String name = text(thread, "name", "unknown");
            String id = text(thread, "id", "");
            String parentId = text(thread, "parent_id", "");
            String parentName = channelNames.getOrDefault(parentId, parentId.isBlank() ? "unknown" : parentId);
            boolean archived = thread.path("thread_metadata").path("archived").asBoolean(false);
            formatted.add("- " + name + " (ID: " + id + ") in #" + parentName + (archived ? " (archived)" : ""));
        }
        return "Retrieved " + formatted.size() + " active threads:\n" + String.join("\n", formatted);
    }

    @Tool(name = "list_channels_rest", description = "List guild channels through Discord REST without requiring gateway readiness")
    public String listChannelsRest(@ToolParam(description = "Discord server ID", required = false) String guildId) {
        guildId = resolveGuildId(guildId);
        JsonNode channels = getJson("/guilds/" + guildId + "/channels");
        if (!channels.isArray() || channels.isEmpty()) {
            throw new IllegalArgumentException("No channels found by guildId");
        }

        List<String> formatted = new ArrayList<>();
        for (JsonNode channel : channels) {
            formatted.add("- " + channelType(channel.path("type").asInt(-1))
                    + " channel: " + text(channel, "name", "unknown")
                    + " (ID: " + text(channel, "id", "") + ")");
        }
        return "Retrieved " + formatted.size() + " channels:\n" + String.join("\n", formatted);
    }

    private JsonNode getJson(String pathAndQuery) {
        HttpRequest request = HttpRequest.newBuilder(URI.create(DISCORD_API + pathAndQuery))
                .timeout(Duration.ofSeconds(30))
                .header("Authorization", "Bot " + token)
                .header("Accept", "application/json")
                .header("User-Agent", "DolphinDiscordDigest/1.0")
                .GET()
                .build();
        HttpResponse<String> response;
        try {
            response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
        } catch (IOException e) {
            throw new IllegalStateException("Discord REST request failed", e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("Discord REST request interrupted", e);
        }

        if (response.statusCode() == 429) {
            JsonNode body = parseJson(response.body());
            String retry = body.path("retry_after").asText("unknown");
            throw new IllegalStateException("Discord REST rate limited; retry_after=" + retry);
        }
        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            throw new IllegalStateException("Discord REST request failed: HTTP " + response.statusCode() + " " + response.body());
        }
        return parseJson(response.body());
    }

    private JsonNode parseJson(String raw) {
        try {
            return objectMapper.readTree(raw == null || raw.isBlank() ? "{}" : raw);
        } catch (IOException e) {
            throw new IllegalStateException(
                    "Discord REST returned invalid JSON: " + preview(raw),
                    e
            );
        }
    }

    private String preview(String raw) {
        if (raw == null) {
            return "";
        }
        String normalized = raw.replaceAll("\\s+", " ").trim();
        return normalized.length() <= 300 ? normalized : normalized.substring(0, 300);
    }

    private Map<String, String> channelNamesById(String guildId) {
        JsonNode channels = getJson("/guilds/" + guildId + "/channels");
        Map<String, String> names = new HashMap<>();
        if (channels.isArray()) {
            for (JsonNode channel : channels) {
                names.put(text(channel, "id", ""), text(channel, "name", "unknown"));
            }
        }
        return names;
    }

    private String formatMessage(JsonNode message) {
        String id = text(message, "id", "");
        String authorName = text(message.path("author"), "global_name", "");
        if (authorName.isBlank()) {
            authorName = text(message.path("author"), "username", "Unknown");
        }
        String timestamp = text(message, "timestamp", "");
        String content = text(message, "content", "").replace("```", "'''");

        StringBuilder builder = new StringBuilder();
        builder.append("- (ID: ")
                .append(id)
                .append(") **[")
                .append(authorName)
                .append("]** `")
                .append(timestamp)
                .append("`: ```")
                .append(content)
                .append("```");

        JsonNode attachments = message.path("attachments");
        if (attachments.isArray() && !attachments.isEmpty()) {
            builder.append("\n  Attachments:");
            for (JsonNode attachment : attachments) {
                builder.append("\n    - (Attachment ID: ")
                        .append(text(attachment, "id", ""))
                        .append(") `")
                        .append(text(attachment, "filename", "attachment"))
                        .append("` URL: ")
                        .append(text(attachment, "url", ""));
            }
        }
        return builder.toString();
    }

    private String resolveGuildId(String guildId) {
        if ((guildId == null || guildId.isBlank()) && defaultGuildId != null && !defaultGuildId.isBlank()) {
            return defaultGuildId;
        }
        if (guildId == null || guildId.isBlank()) {
            throw new IllegalArgumentException("guildId cannot be null");
        }
        return guildId;
    }

    private int parseMessageLimit(String count) {
        if (count == null || count.isBlank()) {
            return 100;
        }
        try {
            int limit = Integer.parseInt(count);
            if (limit < 1 || limit > 100) {
                throw new IllegalArgumentException("count must be between 1 and 100");
            }
            return limit;
        } catch (NumberFormatException ex) {
            throw new IllegalArgumentException("count must be an integer between 1 and 100");
        }
    }

    private void validateCursorParameters(String before, String after, String around) {
        int providedCursors = (isProvided(before) ? 1 : 0)
                + (isProvided(after) ? 1 : 0)
                + (isProvided(around) ? 1 : 0);
        if (providedCursors > 1) {
            throw new IllegalArgumentException("before, after, and around are mutually exclusive; provide only one");
        }
    }

    private boolean isProvided(String value) {
        return value != null && !value.isBlank();
    }

    private String text(JsonNode node, String field, String fallback) {
        JsonNode value = node.path(field);
        return value.isMissingNode() || value.isNull() ? fallback : value.asText(fallback);
    }

    private String urlEncode(String value) {
        return URLEncoder.encode(value, StandardCharsets.UTF_8);
    }

    private String channelType(int type) {
        return switch (type) {
            case 0 -> "TEXT";
            case 2 -> "VOICE";
            case 4 -> "CATEGORY";
            case 5 -> "NEWS";
            case 10 -> "NEWS_THREAD";
            case 11 -> "PUBLIC_THREAD";
            case 12 -> "PRIVATE_THREAD";
            case 13 -> "STAGE";
            case 15 -> "FORUM";
            default -> "TYPE_" + type;
        };
    }
}

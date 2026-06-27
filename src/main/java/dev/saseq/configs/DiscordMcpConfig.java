package dev.saseq.configs;

import dev.saseq.services.DiscordService;
import dev.saseq.services.MessageService;
import dev.saseq.services.UserService;
import dev.saseq.services.ChannelService;
import dev.saseq.services.CategoryService;
import dev.saseq.services.WebhookService;
import dev.saseq.services.ThreadService;
import dev.saseq.services.ModerationService;
import dev.saseq.services.RoleService;
import dev.saseq.services.VoiceChannelService;
import dev.saseq.services.ScheduledEventService;
import dev.saseq.services.InviteService;
import dev.saseq.services.ChannelPermissionService;
import dev.saseq.services.EmojiService;
import dev.saseq.services.ForumService;
import net.dv8tion.jda.api.JDA;
import net.dv8tion.jda.api.JDABuilder;
import net.dv8tion.jda.api.requests.GatewayIntent;
import org.springframework.ai.tool.ToolCallbackProvider;
import org.springframework.ai.tool.method.MethodToolCallbackProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

@Configuration
public class DiscordMcpConfig {
    @Bean
    public ToolCallbackProvider discordTools(DiscordService discordService,
                                             MessageService messageService,
                                             UserService userService,
                                             ChannelService channelService,
                                             CategoryService categoryService,
                                             WebhookService webhookService,
                                             ThreadService threadService,
                                             RoleService roleService,
                                             ModerationService moderationService,
                                             VoiceChannelService voiceChannelService,
                                             ScheduledEventService scheduledEventService,
                                             InviteService inviteService,
                                             ChannelPermissionService channelPermissionService,
                                             EmojiService emojiService,
                                             ForumService forumService) {
        return MethodToolCallbackProvider.builder().toolObjects(
                discordService,
                messageService,
                userService,
                channelService,
                categoryService,
                webhookService,
                threadService,
                roleService,
                moderationService,
                voiceChannelService,
                scheduledEventService,
                inviteService,
                channelPermissionService,
                emojiService,
                forumService
        ).build();
    }

    @Bean
    public JDA jda(@Value("${DISCORD_TOKEN:}") String token) {
        if (token == null || token.isEmpty()) {
            System.err.println("ERROR: The environment variable DISCORD_TOKEN is not set. Please set it to run the application properly.");
            System.exit(1);
        }
        return (JDA) Proxy.newProxyInstance(
                JDA.class.getClassLoader(),
                new Class<?>[]{JDA.class},
                new LazyJdaInvocationHandler(token)
        );
    }

    private static final class LazyJdaInvocationHandler implements InvocationHandler {
        private final CompletableFuture<JDA> jdaFuture;
        private volatile JDA readyJda;

        LazyJdaInvocationHandler(String token) {
            ExecutorService executor = Executors.newSingleThreadExecutor(runnable -> {
                Thread thread = new Thread(runnable, "discord-jda-connect");
                thread.setDaemon(false);
                return thread;
            });
            this.jdaFuture = CompletableFuture.supplyAsync(() -> {
                try {
                    return JDABuilder.createDefault(token)
                            .enableIntents(GatewayIntent.GUILD_MEMBERS, GatewayIntent.GUILD_VOICE_STATES, GatewayIntent.SCHEDULED_EVENTS)
                            .build()
                            .awaitReady();
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    throw new IllegalStateException("Discord client startup was interrupted", e);
                }
            }, executor);
        }

        @Override
        public Object invoke(Object proxy, Method method, Object[] args) throws Throwable {
            if (method.getDeclaringClass() == Object.class) {
                return method.invoke(this, args);
            }

            JDA jda = readyJda;
            if (jda == null) {
                if (!jdaFuture.isDone()) {
                    throw new IllegalStateException("Discord client is still connecting; retry shortly.");
                }
                jda = jdaFuture.get();
                readyJda = jda;
            }
            return method.invoke(jda, args);
        }
    }
}

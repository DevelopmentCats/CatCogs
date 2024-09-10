import discord
from redbot.core import commands, Config
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS
from discord.ext import tasks
import asyncio
import textwrap

class ChannelMirror(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        default_guild = {
            "mirror_pairs": {},  # {target_channel_id: {source_channel_id: source_guild_id}}
            "mirrored_messages": {},
            "last_mirrored_id": {}  # {source_channel_id: last_mirrored_message_id}
        }
        self.config.register_guild(**default_guild)
        self.mirror_task.start()

    def cog_unload(self):
        self.mirror_task.cancel()

    @commands.group()
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def mirror(self, ctx):
        """Manage channel mirroring."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @mirror.command(name="add")
    async def add_mirror(self, ctx, source: discord.TextChannel, target: discord.TextChannel = None):
        """Add a new channel mirror pair.
        
        If target is not specified, it uses the current channel as the target.
        The source channel can be from any server the bot is in.
        """
        if target is None:
            target = ctx.channel

        if target.guild != ctx.guild:
            return await ctx.send("The target channel must be in this server.")

        async with self.config.guild(ctx.guild).mirror_pairs() as pairs:
            if str(target.id) not in pairs:
                pairs[str(target.id)] = {}
            
            if str(source.id) in pairs[str(target.id)]:
                return await ctx.send("This source channel is already being mirrored to this target channel.")
            
            pairs[str(target.id)][str(source.id)] = source.guild.id

        # Mirror only the last message when a new pair is added
        async for message in source.history(limit=1):
            await self.mirror_message(ctx.guild, message, target)
            async with self.config.guild(ctx.guild).last_mirrored_id() as last_mirrored:
                last_mirrored[str(source.id)] = message.id

        embed = discord.Embed(title="Mirror Added", color=discord.Color.green())
        embed.add_field(name="Source Channel", value=f"{source.name} (Server: {source.guild.name})", inline=False)
        embed.add_field(name="Target Channel", value=target.mention, inline=False)
        embed.set_footer(text="Messages will now be mirrored from the source to the target channel.")
        await ctx.send(embed=embed)

    @mirror.command(name="remove")
    async def remove_mirror(self, ctx, target: discord.TextChannel = None):
        """Remove all mirror pairs for a target channel.
        
        If target is not specified, it uses the current channel as the target.
        """
        if target is None:
            target = ctx.channel

        async with self.config.guild(ctx.guild).mirror_pairs() as pairs:
            if str(target.id) not in pairs:
                return await ctx.send("This channel is not set up as a mirror target.")
            
            removed_sources = pairs.pop(str(target.id))

        async with self.config.guild(ctx.guild).last_mirrored_id() as last_mirrored:
            for source_id in removed_sources:
                last_mirrored.pop(str(source_id), None)

        embed = discord.Embed(title="Mirrors Removed", color=discord.Color.red())
        embed.add_field(name="Target Channel", value=target.mention, inline=False)
        embed.add_field(name="Removed Source Channels", value=len(removed_sources), inline=False)
        embed.set_footer(text="Messages will no longer be mirrored to this channel.")
        await ctx.send(embed=embed)

    @mirror.command(name="list")
    async def list_mirrors(self, ctx):
        """List all channel mirror pairs."""
        pairs = await self.config.guild(ctx.guild).mirror_pairs()
        if not pairs:
            return await ctx.send("No channel mirrors set up.")

        embeds = []
        for target_id, sources in pairs.items():
            target_channel = ctx.guild.get_channel(int(target_id))
            if target_channel:
                embed = discord.Embed(title=f"Mirror Target: #{target_channel.name}", color=discord.Color.blue())
                for source_id, source_guild_id in sources.items():
                    source_guild = self.bot.get_guild(source_guild_id)
                    source_channel = self.bot.get_channel(int(source_id))
                    if source_channel:
                        embed.add_field(name=f"Source: {source_guild.name if source_guild else 'Unknown Server'}", 
                                        value=f"#{source_channel.name}", 
                                        inline=False)
                    else:
                        embed.add_field(name=f"Source: Guild ID {source_guild_id}", 
                                        value=f"Channel ID: {source_id} (Not Found)", 
                                        inline=False)
                embeds.append(embed)

        if embeds:
            await menu(ctx, embeds, DEFAULT_CONTROLS)
        else:
            await ctx.send("No valid mirror pairs found.")

    @mirror.command(name="status")
    async def mirror_status(self, ctx):
        """Show the status of the channel mirror system."""
        pairs = await self.config.guild(ctx.guild).mirror_pairs()
        mirrored_count = len(await self.config.guild(ctx.guild).mirrored_messages())

        total_sources = sum(len(sources) for sources in pairs.values())

        embed = discord.Embed(title="Channel Mirror Status", color=discord.Color.blue())
        embed.add_field(name="Target Channels", value=str(len(pairs)), inline=True)
        embed.add_field(name="Total Source Channels", value=str(total_sources), inline=True)
        embed.add_field(name="Total Mirrored Messages", value=str(mirrored_count), inline=False)
        embed.set_footer(text="Use 'mirror list' to see all mirror pairs.")
        await ctx.send(embed=embed)

    @tasks.loop(seconds=30)
    async def mirror_task(self):
        for guild in self.bot.guilds:
            pairs = await self.config.guild(guild).mirror_pairs()
            last_mirrored = await self.config.guild(guild).last_mirrored_id()
            for target_id, sources in pairs.items():
                target_channel = guild.get_channel(int(target_id))
                if not target_channel:
                    continue

                for source_id, source_guild_id in sources.items():
                    source_channel = self.bot.get_channel(int(source_id))
                    if not source_channel:
                        continue

                    last_message_id = last_mirrored.get(source_id, None)
                    async for message in source_channel.history(limit=None, after=discord.Object(id=last_message_id) if last_message_id else None):
                        await self.mirror_message(guild, message, target_channel)
                        last_mirrored[source_id] = message.id

            await self.config.guild(guild).last_mirrored_id.set(last_mirrored)

    async def mirror_message(self, guild, message, target_channel):
        embed = discord.Embed(description=message.content, 
                              timestamp=message.created_at,
                              color=discord.Color.random())
        embed.set_author(name=f"{message.author.name} (Server: {message.guild.name})", 
                         icon_url=message.author.avatar.url)
        
        if message.attachments:
            embed.set_image(url=message.attachments[0].url)

        if len(message.attachments) > 1:
            embed.add_field(name="Additional Attachments", 
                            value="\n".join([f"[{a.filename}]({a.url})" for a in message.attachments[1:]]))

        embed.add_field(name="Original Message", 
                        value=f"[Jump to message]({message.jump_url})", 
                        inline=False)

        mirrored_message = await target_channel.send(embed=embed)

        async with self.config.guild(guild).mirrored_messages() as mirrored:
            mirrored[str(message.id)] = mirrored_message.id

    @commands.command()
    async def mirrorhelp(self, ctx):
        """Display a help message for the Channel Mirror cog."""
        help_text = textwrap.dedent("""
        🔄 **Channel Mirror Help** 🔄

        This cog allows you to mirror messages from channels in other servers to channels in this server.

        **Commands:**
        • `mirror add <source> [target]`: Add a new mirror pair
        • `mirror remove [target]`: Remove all mirrors for a target channel
        • `mirror list`: List all mirror pairs
        • `mirror status`: Show mirror system status

        **Examples:**
        ```
        [p]mirror add #announcements #mirror-channel
        [p]mirror add 1234567890 #mirror-channel
        [p]mirror remove #mirror-channel
        [p]mirror list
        [p]mirror status
        ```

        Replace `[p]` with your bot's command prefix.
        Note: The source channel can be from any server the bot is in, but the target must be in this server.
        If no target is specified, the current channel is used.
        """)

        embed = discord.Embed(title="Channel Mirror Help", 
                              description=help_text, 
                              color=discord.Color.blue())
        embed.set_footer(text="For more information, use [p]help mirror")
        await ctx.send(embed=embed)

def setup(bot):
    bot.add_cog(ChannelMirror(bot))

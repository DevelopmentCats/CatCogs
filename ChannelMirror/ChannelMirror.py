import discord
from redbot.core import commands, Config
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS
from redbot.core.utils.chat_formatting import box, pagify
from discord.ext import tasks
import asyncio
import textwrap

class ChannelMirror(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        default_guild = {
            "mirror_pairs": {},  # {target_channel_id: {source_guild_id: source_channel_id}}
            "mirrored_messages": {}
        }
        self.config.register_guild(**default_guild)
        self.mirror_task.start()

    def cog_unload(self):
        self.mirror_task.cancel()

    @commands.group()
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def channelmirror(self, ctx):
        """Manage channel mirroring."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @channelmirror.command(name="add")
    async def add_mirror(self, ctx, source_channel: discord.TextChannel, target_channel: discord.TextChannel):
        """Add a new channel mirror pair."""
        if target_channel.guild != ctx.guild:
            return await ctx.send("The target channel must be in this server.")

        async with self.config.guild(ctx.guild).mirror_pairs() as pairs:
            if str(target_channel.id) not in pairs:
                pairs[str(target_channel.id)] = {}
            
            if str(source_channel.guild.id) in pairs[str(target_channel.id)]:
                return await ctx.send("This source channel is already being mirrored to this target channel.")
            
            pairs[str(target_channel.id)][str(source_channel.guild.id)] = source_channel.id

        embed = discord.Embed(title="Mirror Added", color=discord.Color.green())
        embed.add_field(name="Source Channel", value=f"{source_channel.mention} (Server: {source_channel.guild.name})", inline=False)
        embed.add_field(name="Target Channel", value=target_channel.mention, inline=False)
        embed.set_footer(text="Messages will now be mirrored from the source to the target channel.")
        await ctx.send(embed=embed)

    @channelmirror.command(name="remove")
    async def remove_mirror(self, ctx, target_channel: discord.TextChannel, source_guild_id: int):
        """Remove a channel mirror pair."""
        async with self.config.guild(ctx.guild).mirror_pairs() as pairs:
            if str(target_channel.id) not in pairs:
                return await ctx.send("This target channel is not set up for mirroring.")
            
            if str(source_guild_id) not in pairs[str(target_channel.id)]:
                return await ctx.send("This source guild is not being mirrored to this target channel.")
            
            source_channel_id = pairs[str(target_channel.id)].pop(str(source_guild_id))
            if not pairs[str(target_channel.id)]:
                del pairs[str(target_channel.id)]

        embed = discord.Embed(title="Mirror Removed", color=discord.Color.red())
        embed.add_field(name="Source Channel", value=f"Channel ID: {source_channel_id} (Server ID: {source_guild_id})", inline=False)
        embed.add_field(name="Target Channel", value=target_channel.mention, inline=False)
        embed.set_footer(text="Messages will no longer be mirrored from this source to the target channel.")
        await ctx.send(embed=embed)

    @channelmirror.command(name="list")
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
                for source_guild_id, source_channel_id in sources.items():
                    source_guild = self.bot.get_guild(int(source_guild_id))
                    source_channel = source_guild.get_channel(source_channel_id) if source_guild else None
                    if source_channel:
                        embed.add_field(name=f"Source: {source_guild.name}", value=f"#{source_channel.name} (ID: {source_channel_id})", inline=False)
                    else:
                        embed.add_field(name=f"Source: Guild ID {source_guild_id}", value=f"Channel ID: {source_channel_id} (Not Found)", inline=False)
                embeds.append(embed)

        if embeds:
            await menu(ctx, embeds, DEFAULT_CONTROLS)
        else:
            await ctx.send("No valid mirror pairs found.")

    @channelmirror.command(name="status")
    async def mirror_status(self, ctx):
        """Show the status of the channel mirror system."""
        pairs = await self.config.guild(ctx.guild).mirror_pairs()
        mirrored_count = len(await self.config.guild(ctx.guild).mirrored_messages())

        total_sources = sum(len(sources) for sources in pairs.values())

        embed = discord.Embed(title="Channel Mirror Status", color=discord.Color.blue())
        embed.add_field(name="Target Channels", value=str(len(pairs)), inline=True)
        embed.add_field(name="Total Source Channels", value=str(total_sources), inline=True)
        embed.add_field(name="Total Mirrored Messages", value=str(mirrored_count), inline=False)
        embed.set_footer(text="Use 'channelmirror list' to see all mirror pairs.")
        await ctx.send(embed=embed)

    @tasks.loop(seconds=30)
    async def mirror_task(self):
        for guild in self.bot.guilds:
            pairs = await self.config.guild(guild).mirror_pairs()
            for target_id, sources in pairs.items():
                target_channel = guild.get_channel(int(target_id))
                if not target_channel:
                    continue

                for source_guild_id, source_channel_id in sources.items():
                    source_guild = self.bot.get_guild(int(source_guild_id))
                    if not source_guild:
                        continue
                    source_channel = source_guild.get_channel(source_channel_id)
                    if not source_channel:
                        continue

                    async for message in source_channel.history(limit=10):
                        if not await self.is_message_mirrored(guild, message.id):
                            await self.mirror_message(guild, message, target_channel)
                            await asyncio.sleep(1)  # Avoid rate limiting

    async def is_message_mirrored(self, guild, message_id):
        async with self.config.guild(guild).mirrored_messages() as mirrored:
            return str(message_id) in mirrored

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
    async def channelmirrorhelp(self, ctx):
        """Display a beautiful help message for the Channel Mirror cog."""
        help_text = textwrap.dedent("""
        🔄 **Channel Mirror Help** 🔄

        This cog allows you to mirror messages from channels in other servers to channels in this server.

        **Commands:**
        • `channelmirror add <source> <target>`: Add a new mirror pair
        • `channelmirror remove <target> <source_guild_id>`: Remove a mirror pair
        • `channelmirror list`: List all mirror pairs
        • `channelmirror status`: Show mirror system status

        **Examples:**
        ```
        [p]channelmirror add #announcements #mirror-announcements
        [p]channelmirror remove #mirror-announcements 123456789
        [p]channelmirror list
        [p]channelmirror status
        ```

        Replace `[p]` with your bot's command prefix.
        Note: The source channel can be from any server the bot is in, but the target must be in this server.
        """)

        embed = discord.Embed(title="Channel Mirror Help", 
                              description=help_text, 
                              color=discord.Color.blue())
        embed.set_footer(text="For more information, use [p]help channelmirror")
        await ctx.send(embed=embed)

def setup(bot):
    bot.add_cog(ChannelMirror(bot))

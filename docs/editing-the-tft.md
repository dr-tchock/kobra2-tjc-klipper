# Rebuilding the screen firmware (USART HMI)

You only need this to change what is stored in the screen (fonts, icons,
boot animation). Layouts and behaviour live in `screen/` and need no
rebuild.

The editor is TJC's **USART HMI** (free, Windows, [tjc1688.com](http://www.tjc1688.com)).
It is Chinese-only and can't be translated (the program is encrypted), so
this guide gives the Chinese labels with translations.

## Useful labels

| Chinese | English | | Chinese | English |
|---|---|---|---|---|
| 文件 | File | | 编译 | Compile |
| 工具 | Tools | | 调试 | Debug (simulator) |
| 新建 / 打开 / 保存 | New / Open / Save | | 输出生产文件 | Output production file (.tft) |
| 工具箱 | Toolbox | | 属性 | Properties |
| 事件 | Events | | 前初始化事件 | Pre-initialise event |
| 图片 / 字库 / 动画 | Pictures / Fonts / Animation | | 确定 / 是 | OK / Yes |
| 字库制作工具 | Font tool | | 生成字库 | Generate font |
| 字高 / 编码 / 字体 | Height / Encoding / Font | | 范围 → 指定字符 | Range → specified characters |
| 字体抗锯齿 | Anti-aliasing | | 0 个错误 | 0 errors |

## Steps

1. **New project** (新建): device **TJC4827X243_011**, display direction
   **90°** (portrait), encoding **utf-8**.
2. **Page 0** (click an empty spot) → 事件 → **前初始化事件**: `baud=115200`.
3. **Fonts**: install Roboto (`tools/fetch_fonts.sh`, then Windows → Install),
   open the font tool from 工具. For each size **16, 20, 24, 32, 48**, in
   that order:
   - 字高 = size, 编码 = utf-8, 字体 = Roboto, 字体抗锯齿 ticked;
   - 范围 = 指定字符; paste the contents of `assets/fonts/charset.txt` into
     the box that appears **below** the dialog;
   - name `roboto<size>`, 生成字库, then 是 to add it.

   The 字库 tab must list them as IDs 0–4 in that order.
   (The generated `.zi` files are also in `tft/fonts/`; the 字库 tab's **+**
   imports them directly.)
4. **Icons**: 图片 tab → **+** → select all `assets/icons/[0-9]*.png`. Check
   that ID 0 is the grey home icon and ID 66 the small fan.
5. **Boot animation**: 动画 tab → **+** → `assets/boot/boot.gif`. Then
   工具箱 → 动画 places `gm0`; set `vid` (browse → the animation),
   `loop` = 否 (no), `en` = 1.
6. **编译** (compile): the output must end with **0 个错误**.
7. **文件 → 输出生产文件**: writes the `.tft`. Flash it as in
   [tft/README.md](../tft/README.md).

The repo's `kobra2.tft` was built exactly this way (pictures 23 KB, fonts
26 KB, animation 3.2 MB, file 3.9 MB).

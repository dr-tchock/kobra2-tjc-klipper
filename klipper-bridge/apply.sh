#!/bin/sh
# Add the HC32F460 serial bridge to a Klipper source tree (idempotent).
# Usage: ./apply.sh /path/to/klipper
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
KL=${1:?usage: apply.sh /path/to/klipper}

cp "$HERE/src/hc32f460/serial_bridge.c" "$KL/src/hc32f460/"

if ! grep -q HC32F460_SERIAL_BRIDGE "$KL/src/hc32f460/Kconfig"; then
    # Insert right after the communication interface choice
    awk '
        { print }
        /^endchoice/ && !done {
            print ""
            print "config HC32F460_SERIAL_BRIDGE"
            print "    bool \"Serial bridge on USART4 (PH2 RX / PB10 TX) for a UART display\""
            print "    depends on SERIAL && !HC32F460_SERIAL_PH2_PB10"
            print "    default n"
            done = 1
        }
    ' "$KL/src/hc32f460/Kconfig" > "$KL/src/hc32f460/Kconfig.new"
    mv "$KL/src/hc32f460/Kconfig.new" "$KL/src/hc32f460/Kconfig"
fi

if ! grep -q serial_bridge "$KL/src/hc32f460/Makefile"; then
    sed -i '/^src-\$(CONFIG_SERIAL) += hc32f460\/serial.c/a src-$(CONFIG_HC32F460_SERIAL_BRIDGE) += hc32f460/serial_bridge.c' \
        "$KL/src/hc32f460/Makefile"
fi
grep -q serial_bridge "$KL/src/hc32f460/Makefile" || {
    echo "Makefile patch failed" >&2; exit 1; }

# Fix TX handling in the main serial driver. Upstream turns the transmitter
# off on every TX-complete irq, even when a new message started meanwhile,
# which cuts bytes (host sees bytes_invalid). It can't simply stay on either:
# HC32F460 errata 2.6.1 - the TX-empty irq only fires when TE and TXEIE are
# set together while TE=0. So restarts go through the TX-complete irq.
python3 - "$KL/src/hc32f460/serial.c" <<'EOF'
import sys
path = sys.argv[1]
src = open(path).read()
if "tx_restart" in src:
    sys.exit(0)
reps = [
("""#include "sched.h"      // DECL_INIT
""", """#include "sched.h"      // DECL_INIT
#include "board/irq.h"  // irq_save
"""),
("""void
serialTxComplete(void)
{
    USART_FuncCmd(USARTx, UsartTx, Disable);
    USART_FuncCmd(USARTx, UsartTxCmpltInt, Disable);
}""", """static volatile uint8_t tx_restart;

void
serialTxComplete(void)
{
    // Last byte is out - stop the transmitter, restart it if data was
    // queued while it was finishing (see serial_enable_tx_irq)
    USART_FuncCmd(USARTx, UsartTxCmpltInt, Disable);
    USART_FuncCmd(USARTx, UsartTx, Disable);
    if (tx_restart) {
        tx_restart = 0;
        USART_FuncCmd(USARTx, UsartTxAndTxEmptyInt, Enable);
    }
}"""),
("""serial_enable_tx_irq(void)
{
    /* Enable TX && TX empty interrupt */
    USART_FuncCmd(USARTx, UsartTxAndTxEmptyInt, Enable);
}""", """serial_enable_tx_irq(void)
{
    // HC32F460 errata 2.6.1: the TX empty irq only fires when TE and TXEIE
    // are set together while TE=0
    irqstatus_t flag = irq_save();
    if (!USARTx->CR1_f.TE)
        USART_FuncCmd(USARTx, UsartTxAndTxEmptyInt, Enable);
    else if (!USARTx->CR1_f.TXEIE)
        // Finishing the previous message - TX complete irq restarts us
        tx_restart = 1;
    // else: transmitting, the TX empty irq picks up the new data
    irq_restore(flag);
}"""),
]
for old, new in reps:
    if old not in src:
        sys.exit("serial.c changed upstream - TX patch needs review")
    src = src.replace(old, new)
open(path, "w").write(src)
EOF
echo "serial bridge applied to $KL"

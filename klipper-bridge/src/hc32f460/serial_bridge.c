// HC32F460 serial bridge - forward a spare USART to the host
//
// Used for the Anycubic Kobra 2 TJC display: USART4, TX=PB10 RX=PH2
// (same pins/peripheral as Anycubic's stock firmware, LCD_SERIAL_PORT 4).
//
// This file may be distributed under the terms of the GNU GPLv3 license.

#include "autoconf.h" // CONFIG_CLOCK_FREQ
#include "basecmd.h" // oid_alloc
#include "board/irq.h" // irq_save
#include "board/misc.h" // timer_read_time
#include "command.h" // DECL_COMMAND
#include "sched.h" // DECL_TASK
#include "generic/armcm_boot.h" // DECL_ARMCM_IRQ
#include "internal.h" // IrqRegistration

#include "hc32f460_usart.h"
#include "hc32f460_gpio.h"
#include "hc32f460_pwc.h"

DECL_CONSTANT_STR("RESERVE_PINS_serial_bridge", "PH2,PB10");

#define BR_USART        M4_USART4
#define BR_RX_PORT      PortH
#define BR_RX_PIN       Pin02
#define BR_TX_PORT      PortB
#define BR_TX_PIN       Pin10

// Main serial uses Int000..Int003, the bridge takes the next four
#define BR_IRQ_RI       Int004_IRQn
#define BR_IRQ_EI       Int005_IRQn
#define BR_IRQ_TI       Int006_IRQn
#define BR_IRQ_TCI      Int007_IRQn

// Ring buffers; uint8_t indexes wrap at 256 for free
#define BUF_SIZE 256
// Payload per message, keeps frames well inside MESSAGE_MAX (64)
#define CHUNK 48
// Forward received data once the line was quiet for this many byte times
#define IDLE_BYTES 3

// Bits reported in serial_bridge_data flags
#define FL_RX_OVERFLOW  0x01
#define FL_TX_OVERFLOW  0x02
#define FL_FRAME_ERROR  0x04

struct serial_bridge {
    uint8_t oid, configured;
    volatile uint8_t rx_head, rx_tail, tx_head, tx_tail, flags;
    volatile uint32_t last_rx;
    uint32_t idle_ticks;
    uint8_t rx_buf[BUF_SIZE], tx_buf[BUF_SIZE];
};

static struct serial_bridge *bridge;
static struct task_wake bridge_wake;


/****************************************************************
 * Interrupt handlers
 ****************************************************************/

static void
bridge_rx_byte(uint8_t data)
{
    if (!bridge)
        return;
    bridge->last_rx = timer_read_time();
    uint8_t next = bridge->rx_head + 1;
    if (next == bridge->rx_tail) {
        bridge->flags |= FL_RX_OVERFLOW;
        return;
    }
    bridge->rx_buf[bridge->rx_head] = data;
    bridge->rx_head = next;
    sched_wake_task(&bridge_wake);
}

void
bridge_rx_irq(void)
{
    bridge_rx_byte(USART_RecData(BR_USART));
}
DECL_ARMCM_IRQ(bridge_rx_irq, BR_IRQ_RI);

void
bridge_err_irq(void)
{
    if (USART_GetStatus(BR_USART, UsartFrameErr) == Set) {
        USART_ClearStatus(BR_USART, UsartFrameErr);
        // Same as the main serial driver: keep the byte, but report it
        if (bridge)
            bridge->flags |= FL_FRAME_ERROR;
        bridge_rx_byte(BR_USART->DR_f.RDR);
    }
    if (USART_GetStatus(BR_USART, UsartParityErr) == Set)
        USART_ClearStatus(BR_USART, UsartParityErr);
    if (USART_GetStatus(BR_USART, UsartOverrunErr) == Set) {
        USART_ClearStatus(BR_USART, UsartOverrunErr);
        if (bridge)
            bridge->flags |= FL_RX_OVERFLOW;
    }
}
DECL_ARMCM_IRQ(bridge_err_irq, BR_IRQ_EI);

void
bridge_tx_irq(void)
{
    if (bridge && bridge->tx_tail != bridge->tx_head) {
        USART_SendData(BR_USART, bridge->tx_buf[bridge->tx_tail]);
        bridge->tx_tail++;
    } else {
        // Nothing left - wait for the last byte to leave the shifter
        USART_FuncCmd(BR_USART, UsartTxCmpltInt, Enable);
        USART_FuncCmd(BR_USART, UsartTxEmptyInt, Disable);
    }
}
DECL_ARMCM_IRQ(bridge_tx_irq, BR_IRQ_TI);

void
bridge_tc_irq(void)
{
    // Last byte is out - stop the transmitter, and restart it if a send
    // command queued more data while it was finishing (errata 2.6.1: the
    // TX empty irq only fires when TE and TXEIE are set together from TE=0)
    USART_FuncCmd(BR_USART, UsartTxCmpltInt, Disable);
    USART_FuncCmd(BR_USART, UsartTx, Disable);
    if (bridge && bridge->tx_tail != bridge->tx_head)
        USART_FuncCmd(BR_USART, UsartTxAndTxEmptyInt, Enable);
}
DECL_ARMCM_IRQ(bridge_tc_irq, BR_IRQ_TCI);


/****************************************************************
 * Commands
 ****************************************************************/

void
command_config_serial_bridge(uint32_t *args)
{
    if (bridge)
        shutdown("Only one serial_bridge supported");
    bridge = oid_alloc(args[0], command_config_serial_bridge
                       , sizeof(*bridge));
    bridge->oid = args[0];
    uint32_t baud = args[1];
    bridge->idle_ticks = (uint64_t)CONFIG_CLOCK_FREQ * 10 * IDLE_BYTES / baud;

    const stc_usart_uart_init_t cfg = {
        UsartIntClkCkNoOutput,
        UsartClkDiv_1,
        UsartDataBits8,
        UsartDataLsbFirst,
        UsartOneStopBit,
        UsartParityNone,
        UsartSampleBit16,
        UsartStartBitFallEdge,
        UsartRtsEnable,
    };
    PWC_Fcg1PeriphClockCmd(PWC_FCG1_PERIPH_USART4, Enable);
    PORT_SetFunc(BR_RX_PORT, BR_RX_PIN, Func_Usart4_Rx, Disable);
    PORT_SetFunc(BR_TX_PORT, BR_TX_PIN, Func_Usart4_Tx, Disable);
    if (USART_UART_Init(BR_USART, &cfg) != Ok)
        shutdown("serial_bridge init failed");
    if (USART_SetBaudrate(BR_USART, baud) != Ok)
        shutdown("serial_bridge unsupported baud");

    IrqRegistration(INT_USART4_RI, BR_IRQ_RI);
    IrqRegistration(INT_USART4_EI, BR_IRQ_EI);
    IrqRegistration(INT_USART4_TI, BR_IRQ_TI);
    IrqRegistration(INT_USART4_TCI, BR_IRQ_TCI);

    USART_FuncCmd(BR_USART, UsartRx, Enable);
    USART_FuncCmd(BR_USART, UsartRxInt, Enable);
    bridge->configured = 1;
}
DECL_COMMAND(command_config_serial_bridge,
             "config_serial_bridge oid=%c baud=%u");

void
command_serial_bridge_send(uint32_t *args)
{
    struct serial_bridge *b = oid_lookup(args[0]
                                         , command_config_serial_bridge);
    uint8_t len = args[1], *data = command_decode_ptr(args[2]);
    while (len--) {
        uint8_t next = b->tx_head + 1;
        if (next == b->tx_tail) {
            b->flags |= FL_TX_OVERFLOW;
            sched_wake_task(&bridge_wake);
            break;
        }
        b->tx_buf[b->tx_head] = *data++;
        b->tx_head = next;
    }
    irqstatus_t flag = irq_save();
    if (!BR_USART->CR1_f.TE)
        USART_FuncCmd(BR_USART, UsartTxAndTxEmptyInt, Enable);
    // else: transmitting (tx irq picks up the data) or finishing (tc irq
    // sees the non-empty ring and restarts)
    irq_restore(flag);
}
DECL_COMMAND(command_serial_bridge_send, "serial_bridge_send oid=%c data=%*s");


/****************************************************************
 * Task: forward received bytes to the host
 ****************************************************************/

void
serial_bridge_task(void)
{
    if (!sched_check_wake(&bridge_wake) || !bridge || !bridge->configured)
        return;
    uint8_t tail = bridge->rx_tail, head = bridge->rx_head;
    uint8_t pending = head - tail;
    if (pending && pending < CHUNK
        && timer_is_before(timer_read_time()
                           , bridge->last_rx + bridge->idle_ticks)) {
        // Screen is mid-reply - batch it into one message
        sched_wake_task(&bridge_wake);
        return;
    }
    uint8_t buf[CHUNK], len = 0;
    while (tail != head && len < CHUNK)
        buf[len++] = bridge->rx_buf[tail++];
    bridge->rx_tail = tail;
    irqstatus_t flag = irq_save();
    uint8_t flags = bridge->flags;
    bridge->flags = 0;
    irq_restore(flag);
    if (!len && !flags)
        return;
    sendf("serial_bridge_data oid=%c flags=%c data=%*s"
          , bridge->oid, flags, len, buf);
    if (tail != bridge->rx_head)
        // More data pending - run again on the next pass
        sched_wake_task(&bridge_wake);
}
DECL_TASK(serial_bridge_task);

static void
bridge_stop(void)
{
    if (!bridge || !bridge->configured)
        return;
    USART_FuncCmd(BR_USART, UsartRxInt, Disable);
    USART_FuncCmd(BR_USART, UsartTxEmptyInt, Disable);
    USART_FuncCmd(BR_USART, UsartTxCmpltInt, Disable);
    bridge->configured = 0;
}

void
serial_bridge_shutdown(void)
{
    bridge_stop();
}
DECL_SHUTDOWN(serial_bridge_shutdown);

// Runs at boot and again on config_reset (which frees oid memory)
void
serial_bridge_init(void)
{
    bridge_stop();
    bridge = NULL;
}
DECL_INIT(serial_bridge_init);


/**************************************
*file name:nvic-interface.c
*date:2/9/2022
*made by:mohamed sallam
***************************************/
#ifndef NVIC_INTERFACE_H
#define NVIC_INTERFACE_H



#include "STD_TYPES.h"
void NVIC_en_int_id(u8 );
void NVIC_disable_interrupt(u8 );
void NVIC_set_pending_flag_interrupt(u8 );

u8 NVIC_get_active_bit_interrupt(  u8 );
void NVIC_clear_pending_flag_interrupt( u8 );
void NVIC_SET_priorty(s8  ,u8 ,u8 ,u32 );
void NVIC_INT19_ISR(u32 (*isr_fun)(void));

#define g1_8group_1sub 0x05Fa0400
#define g2_4groups_2sub 0x05Fa0500
#define g3_2groups_4sub 0x05Fa0600
#define g4_1group_8sub 0x05Fa0700
#endif
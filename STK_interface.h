
/**************************************
*file name:stk-interface.h
*date:2/9/2022
*made by:mohamed sallam
***************************************/
#ifndef	STK_INTERFACE_H
#define STK_INTERFACE_H

#define AHB											0
#define AHB_DIV_4								1
/*************************************/
#define STK_SINGLE_INTERVAL			0
#define STK_PERIODICE_INTERVAL	1
#include "STD_TYPES.h"

/* 
 Apply Clock choise from configuration file 
 Disable SysTick Interrupt 
 Disable SysTick 						  */
void MSTK_voidInit(void);

void MSTK_voidSetBusyWaite(u32 );

void MSTK_voidSetIntervalSingle(u32   , void (*copy_ptr)(void));

void MSTK_voidSetIntervalPeriodic(u32 , void (*copy_ptr)(void));

void MSTK_voidStopInterval(void);

u32  MSTK_u32GetElapsedTime(void);

u32  MSTK_u32GetRemainingTime(void);


#endif

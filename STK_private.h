/********************************************/
/* Auther  : mohamed sallam                 */
/* Date	   : 23-8-2022                      */
/* VERSION : final                          */
/********************************************/

#ifndef	STK_PRIVATE_H
#define STK_PRIVATE_H


void (*MSTK_CallBack)(void);

	
#define SYSTICK_INT_ID 15
/**************************************************/
#define STK_CTRL 	*((volatile u32*)(0xE000E010+0x00))
#define STK_LOAD 	*((volatile u32*)(0xE000E010+0x04))
#define STK_VAL 	*((volatile u32*)(0xE000E010+0x08))
#define STK_CALIB *((volatile u32*)(0x0000003C)


#endif

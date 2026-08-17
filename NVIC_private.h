#ifndef NVIC_private_h
#define NVIC_private_h
/* Auther  : mohamed sallam                 */
/* Date	   : 23-8-2022                      */
/* VERSION : final                          */
/********************************************/
/*base adresse 0xE000E100*/
#define NVIC_ENEBLE_INT0	       *((u32*)0xE000E100)
#define NVIC_ENEBLE_INT1		     *((u32*)0xE000E104)



/************************************************/
#define NVIC_clear_INT0		       *((u32*)0xE000E180)
#define NVIC_clear_INT1	         *((u32*)0xE000E184)

/************************************************/
#define NVIC_set_pinding_INT0		 *((u32*)0xE000E200)
#define NVIC_set_pinding_INT1		 *((u32*)0xE000E204)

/************************************************/
#define NVIC_clear_pinding_INT0	 *((u32*)0xE000E280)
#define NVIC_clear_pinding_INT1  *((u32*)0xE000E284)

/************************************************/
#define NVIC_active_bit_INT0 		 *((volatile u32*)0xE000E300)/*using voltaile in read only registers*/
#define NVIC_active_bit_INT1 		 *((volatile u32*)0xE000E304)
#define NVIC_PIR_ptr 							((volatile u8*)0xE00E400)  /*pointer*/
#define APINT 									 *(volatile u32*)0xE000ED0C/*lock is 0x05FA*/ 


#endif

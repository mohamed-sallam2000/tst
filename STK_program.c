
/********************************************/

#include "STD_TYPES.h"
#include "Macros.h"

#include "STK_interface.h"
#include "STK_private.h"
#include "STK_config.h"


/* Define Variable for interval mode */
static u8 MSTK_u8ModeInterval;

/* 
 Apply Clock choice from configuration file
 Disable SysTick Interrupt 
 Disable SysTick 						  */
void MSTK_voidInit(void)/*systick clock=systemclock/8||||||50MHz/8=12.5MHz*/
{
	/* Apply Clock Source */
	#if MSTK_CLOCK_SOURCE   == AHB
	SET_BIT(STK_CTRL,2);
		
	#elif MSTK_CLOCK_SOURCE == AHB_DIV_4
	CLEAR_BIT(STK_CTRL,2);
		
	#else
		 #error("Wrong Clock Type")
	
	#endif
	
	CLEAR_BIT(STK_CTRL,0);		
	CLEAR_BIT(STK_CTRL,1);		
}


void MSTK_voidSetIntervalPeriodic(u32 u32tick, void (*copy_ptr)(void))
{
	STK_LOAD=u32tick;		   
	MSTK_CallBack=copy_ptr;
	MSTK_u8ModeInterval=STK_PERIODICE_INTERVAL;
	SET_BIT(STK_CTRL,0);	
	SET_BIT(STK_CTRL,1);			 
}
void MSTK_voidSetIntervalSingle(u32 u32tick  , void (*copy_ptr)(void))/*interrupt after one shoot*/
{
	STK_LOAD=u32tick;		     
	MSTK_CallBack=copy_ptr;
	MSTK_u8ModeInterval=STK_SINGLE_INTERVAL;
	SET_BIT(STK_CTRL,0);	    
	SET_BIT(STK_CTRL,1);	
}


void MSTK_voidStopInterval(void)
{
	CLEAR_BIT(STK_CTRL,0);		
	CLEAR_BIT(STK_CTRL,1);	
	STK_LOAD=0;
	STK_VAL =0;
}

u32  MSTK_u32GetElapsedTime(void)
{
	u32 Local_u32Ticks=0;
	Local_u32Ticks = STK_LOAD - STK_VAL;
	return Local_u32Ticks;
}

u32  MSTK_u32GetRemainingTime(void)
{
	u32 Local_u32Ticks=0;
	Local_u32Ticks = STK_VAL;
	return Local_u32Ticks;
}


void SysTick_Handler(void)
{
	volatile u8 Local_u8Temp=0;
	if(MSTK_u8ModeInterval == STK_SINGLE_INTERVAL)
	{
		CLEAR_BIT(STK_CTRL,0);		   /* Disable Timer */        
		CLEAR_BIT(STK_CTRL,1);		     
		STK_LOAD =0;
		STK_VAL  =0;
	}
	MSTK_CallBack();				       
	Local_u8Temp = GET_BIT(STK_CTRL,16); 
}
void MSTK_voidSetBusyWaite(u32 u32tick)
{
	STK_LOAD=u32tick;		   
	SET_BIT(STK_CTRL,0);	    	 
	while(GET_BIT(STK_CTRL,16)==0);  /* waite untile Falg is Set    */
	CLEAR_BIT(STK_CTRL,0);            
	STK_LOAD  = 0;
	STK_VAL   = 0;
}